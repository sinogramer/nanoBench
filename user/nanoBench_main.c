// nanoBench
//
// Copyright (C) 2019 Andreas Abel
//
// This program is free software: you can redistribute it and/or modify it under the terms of version 3 of the GNU Affero General Public License.
//
// This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY
// or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License along with this program. If not, see <https://www.gnu.org/licenses/>.

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <getopt.h>
#include <sys/mman.h>
#include <fcntl.h>
#include <sched.h>
#include <unistd.h>

#include "../common/nanoBench.h"

#if defined(__riscv)
#include "riscv_pmu.h"
#endif

void print_usage() {
    printf("\n");
    printf("nanoBench usage:\n");
    printf("\n");
    printf("  -code <filename>:               Binary file containing the code to be benchmarked.\n");
    printf("  -code_init <filename>:          Binary file containing code to be executed once before each measurement.\n");
    printf("  -code_late_init <filename>:     Binary file containing code to be executed once immediately before the code to be benchmarked.\n");
    printf("  -code_one_time_init <filename>: Binary file containing code to be executed once before the first measurement\n");
    printf("  -config <filename>:             File with performance counter event specifications.\n");
    printf("  -fixed_counters:                Reads the fixed-function performance counters.\n");
    printf("  -n_measurements <n>:            Number of times the measurements are repeated.\n");
    printf("  -unroll_count <n>:              Number of copies of the benchmark code inside the inner loop.\n");
    printf("  -loop_count <n>:                Number of iterations of the inner loop.\n");
    printf("  -warm_up_count <n>:             Number of runs before the first measurement gets recorded.\n");
    printf("  -initial_warm_up_count <n>:     Number of runs before any measurement is performed.\n");
    printf("  -alignment_offset <n>:          Alignment offset.\n");
    printf("  -df:                            Drains front-end buffers between executing code_late_init and code.\n");
    printf("  -avg:                           Selects the arithmetic mean as the aggregate function.\n");
    printf("  -median:                        Selects the median as the aggregate function.\n");
    printf("  -min:                           Selects the minimum as the aggregate function.\n");
    printf("  -basic_mode:                    Enables basic mode.\n");
    printf("  -no_mem:                        The code for reading the perf. ctrs. does not make memory accesses.\n");
    printf("  -no_normalization:              The measurement results are not divided by the number of repetitions.\n");
    printf("  -verbose:                       Outputs the results of all performance counter readings.\n");
    printf("  -cpu <n>:                       Pins the measurement thread to CPU n. \n");
    printf("  -usr <n>:                       If 1, counts events at a privilege level greater than 0.\n");
    printf("  -os <n>:                        If 1, counts events at a privilege level 0.\n");
    printf("  -debug:                         Generate a breakpoint trap after running the code to be benchmarked.\n");
    printf("  -instructions_per_block <n>: Number of measured instructions per block.\n");
    printf("  -measurement <name>:          Measurement type stored in CSV.\n");
    printf("  -csv <filename>:                Appends measurement results to a CSV file.\n");
    printf("  -n_pmc <n>:                     RISC-V: max. number of raw events per run (default: 14).\n");
}

size_t mmap_file(char* filename, char** content) {
    int fd = open(filename, O_RDONLY);
    size_t len = lseek(fd, 0, SEEK_END);
    *content = mmap(0, len, PROT_READ, MAP_PRIVATE, fd, 0);
    if (*content == MAP_FAILED) {
        fprintf(stderr, "Error reading %s\n", filename);
        exit(1);
    }
    close(fd);
    return len;
}

static void write_csv_field(FILE *file, const char *value)
{
    const bool quote = strchr(value, ',') != NULL || strchr(value, '"') != NULL ||
                       strchr(value, '\n') != NULL || strchr(value, '\r') != NULL;

    if (!quote) {
        fputs(value, file);
        return;
    }

    fputc('"', file);

    for (const char *p = value; *p != '\0'; ++p) {
        if (*p == '"') {
            fputc('"', file);
        }

        fputc(*p, file);
    }

    fputc('"', file);
}

static FILE *open_csv_file(const char *path)
{
    FILE *file = fopen(path, "a+");

    if (file == NULL) {
        perror("fopen CSV");
        return NULL;
    }

    if (fseek(file, 0, SEEK_END) != 0) {
        perror("fseek CSV");
        fclose(file);
        return NULL;
    }

    const long size = ftell(file);

    if (size < 0) {
        perror("ftell CSV");
        fclose(file);
        return NULL;
    }

    if (size == 0) {
        fprintf(file, "architecture,core,cpu,code,code_size,measurement,event,selector,value,"
                      "instructions_per_block,value_per_instruction,unroll_count,loop_count,aggregate\n");
    }

    return file;
}

static bool write_csv_result(FILE *file, const char *core, int cpu,
                             const char *code_path, size_t code_size, const char *benchmark_name,
                             const char *measurement, const char *event, const char *selector, 
                             double value, long instructions_per_block,
                             long unroll, long loop, const char *aggregate)
{
    if (file == NULL) {
        return true;
    }

    const char *csv_code_name = benchmark_name != NULL ? benchmark_name : code_path;
    const double value_per_instruction = value / (double)instructions_per_block;

    write_csv_field(file, "riscv64");
    fputc(',', file);
    write_csv_field(file, core);
    fprintf(file, ",%d,", cpu);
    write_csv_field(file, csv_code_name);
    fprintf(file, ",%zu,", code_size);
    write_csv_field(file, measurement);
    fputc(',', file);
    write_csv_field(file, event);
    fputc(',', file);
    write_csv_field(file, selector);
    fprintf(file, ",%.6f,%ld,%.6f,%ld,%ld,", value, instructions_per_block, value_per_instruction, unroll, loop);
    write_csv_field(file, aggregate);
    fputc('\n', file);

    if (fflush(file) != 0) {
        perror("fflush CSV");
        return false;
    }

    return true;
}

#if defined(__riscv)

/* group that is currently measured; used by the seqlock hooks of run_experiment() */
static struct riscv_pmu_group *riscv_active_group;

static void riscv_pre_run(void)
{
    riscv_pmu_group_snapshot(riscv_active_group);
}

static int riscv_post_run(void)
{
    return riscv_pmu_group_check(riscv_active_group);
}

static bool riscv_report(FILE *csv_file, const char *core, int cpu, const char *code_path, size_t code_length,
                         const char *benchmark_name, const char *measurement_name, const char *aggregate_name,
                         long instructions_per_block, int index, char *description, const char *selector)
{
    char buf[200];

    printf("%s", compute_result_str(buf, sizeof(buf), description, index));
    fflush(stdout);

    return write_csv_result(csv_file, core, cpu, code_path, code_length, benchmark_name, measurement_name,
                            description, selector, compute_result_value((size_t)index), instructions_per_block,
                            unroll_count, loop_count, aggregate_name);
}

/*
 * Measures cycles, instret and all raw events of the config file.
 *
 * Each run reads {cycles, instructions, raw_1, ..., raw_k} at the same time:
 * the events are opened as one perf group and the generated code reads all of
 * them with csrr. k is at most n_programmable_counters. If the kernel cannot
 * schedule a group, the raw events are split in halves; a single raw event
 * that does not fit together with cycles/instructions is measured alone.
 */
static int run_riscv_measurements(FILE *csv_file, int cpu, bool usr, bool os,
                                  const char *code_path, size_t code_length, const char *benchmark_name,
                                  const char *measurement_name, const char *aggregate_name,
                                  long instructions_per_block,
                                  long base_unroll_count, long main_unroll_count,
                                  long base_loop_count, long main_loop_count)
{
    const struct riscv_pmu_event fixed[2] = {
        {PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES},
        {PERF_TYPE_HARDWARE, PERF_COUNT_HW_INSTRUCTIONS},
    };

    int max_raw = n_programmable_counters;
    if (max_raw > MAX_PROGRAMMABLE_COUNTERS - 2) max_raw = MAX_PROGRAMMABLE_COUNTERS - 2;
    if (max_raw < 1) max_raw = 1;

    bool fixed_done = !use_fixed_counters;
    size_t next = 0;
    riscv_n_retried_runs = 0;

    const int user_access = riscv_perf_user_access();
    if (user_access != 1) {
        fprintf(stderr, "Warning: kernel.perf_user_access=%d; csrr access to perf events needs 1 "
                        "(sudo sysctl -w kernel.perf_user_access=1)\n", user_access);
    }

    char core[128];
    riscv_cpu_name(cpu, core, sizeof(core));

    while (next < n_pfc_configs || !fixed_done) {
        size_t remaining = n_pfc_configs - next;
        int batch = remaining < (size_t)max_raw ? (int)remaining : max_raw;
        bool with_fixed = true;
        struct riscv_pmu_group group;
        struct riscv_pmu_event events[RISCV_PMU_MAX_EVENTS];
        int rc;

        /* open {cycles, instructions, raw[next .. next+batch)}; shrink until it fits */
        for (;;) {
            int n = 0;

            if (with_fixed) {
                events[n++] = fixed[0];
                events[n++] = fixed[1];
            }
            for (int j = 0; j < batch; ++j) {
                events[n++] = (struct riscv_pmu_event){PERF_TYPE_RAW, pfc_configs[next + (size_t)j].raw_selector};
            }

            rc = riscv_pmu_group_open(&group, events, n, cpu, usr, os);

            if (rc != RISCV_PMU_NOT_SCHEDULED) break;
            if (batch > 1) { batch = (batch + 1) / 2; continue; }
            if (batch == 1 && with_fixed) { with_fixed = false; continue; }
            break;
        }

        if (rc != RISCV_PMU_OK) {
            if (batch == 0) {
                print_error("Could not schedule the cycles/instructions events");
                return 1;
            }
            print_error("Raw event 0x%llx could not be measured; skipped",
                        (unsigned long long)pfc_configs[next].raw_selector);
            next++;
            continue;
        }

        /* tell the code generator which CSRs to read */
        riscv_n_counters = (unsigned int)group.n;
        for (int i = 0; i < group.n; ++i) {
            const uint16_t width = group.ctr[i].width;
            riscv_counter_csr[i] = 0xC00U + group.ctr[i].hardware_index;
            riscv_counter_mask[i] = (width == 0 || width >= 64) ? ~0ULL : ((1ULL << width) - 1);

            if (verbose) {
                char name[32];
                const struct riscv_pmu_event *ev = &events[i];
                fprintf(stderr, "  event %d: %-14s -> hpmcounter%u (CSR 0x%x, width %u)\n", i,
                        riscv_pmu_event_name(ev->type, ev->config, name, sizeof(name)),
                        group.ctr[i].hardware_index, riscv_counter_csr[i], width);
            }
        }

        riscv_active_group = &group;
        riscv_pre_run_hook = riscv_pre_run;
        riscv_post_run_hook = riscv_post_run;

        char *template = (char *)&measurement_template_RISCV_PMC;
        run_experiment(template, measurement_results_base, group.n, base_unroll_count, base_loop_count);
        run_experiment(template, measurement_results, group.n, main_unroll_count, main_loop_count);

        riscv_pre_run_hook = NULL;
        riscv_post_run_hook = NULL;
        riscv_active_group = NULL;

        if (verbose) {
            printf("\nRISC-V counter results (unroll_count=%ld, loop_count=%ld):\n\n", base_unroll_count, base_loop_count);
            print_all_measurement_results(measurement_results_base, group.n);
            printf("RISC-V counter results (unroll_count=%ld, loop_count=%ld):\n\n", main_unroll_count, main_loop_count);
            print_all_measurement_results(measurement_results, group.n);
        }

        bool ok = true;

        if (with_fixed && !fixed_done) {
            ok = riscv_report(csv_file, core, cpu, code_path, code_length, benchmark_name, measurement_name,
                              aggregate_name, instructions_per_block, 0, "Core cycles", "fixed-cycle") &&
                 riscv_report(csv_file, core, cpu, code_path, code_length, benchmark_name, measurement_name,
                              aggregate_name, instructions_per_block, 1, "Instructions retired", "fixed-instret");
            fixed_done = true;
        }

        const int first_raw = with_fixed ? 2 : 0;
        for (int j = 0; ok && j < batch; ++j) {
            struct pfc_config *config = &pfc_configs[next + (size_t)j];
            char selector[32];
            snprintf(selector, sizeof(selector), "0x%llx", (unsigned long long)config->raw_selector);

            ok = riscv_report(csv_file, core, cpu, code_path, code_length, benchmark_name, measurement_name,
                              aggregate_name, instructions_per_block, first_raw + j, config->description, selector);
        }

        riscv_pmu_group_close(&group);

        if (!ok) return 1;
        next += (size_t)batch;
    }

    if (riscv_n_retried_runs > 0) {
        fprintf(stderr, "Note: %ld run(s) were repeated because the kernel reprogrammed the counters\n",
                riscv_n_retried_runs);
    }

    return 0;
}

#endif

int main(int argc, char **argv) {
    /*************************************
     * Parse command-line options
     ************************************/
    char* config_file_name = NULL;
    bool usr = 1;
    bool os = 0;

    const char *csv_path = NULL;
    FILE *csv_file = NULL;
    const char *aggregate_name = "median";
    const char *code_path = "";
    const char *benchmark_name = NULL;
    long instructions_per_block = 1;
    const char *measurement_name = "unspecified";
    int n_pmc_override = 0;

    struct option long_opts[] = {
        {"code", required_argument, 0, 'c'},
        {"code_init", required_argument, 0, 'i'},
        {"code_late_init", required_argument, 0, 't'},
        {"code_one_time_init", required_argument, 0, 'o'},
        {"config", required_argument, 0, 'f'},
        {"fixed_counters", no_argument, &use_fixed_counters, true},
        {"n_measurements", required_argument, 0, 'n'},
        {"unroll_count", required_argument, 0, 'u'},
        {"loop_count", required_argument, 0, 'l'},
        {"warm_up_count", required_argument, 0, 'w'},
        {"initial_warm_up_count", required_argument, 0, 'a'},
        {"alignment_offset", required_argument, 0, 'm'},
        {"df", no_argument, &drain_frontend, true},
        {"avg", no_argument, &aggregate_function, AVG_20_80},
        {"median", no_argument, &aggregate_function, MED},
        {"min", no_argument, &aggregate_function, MIN},
        {"max", no_argument, &aggregate_function, MAX},
        {"range", no_argument, &output_range, true},
        {"basic_mode", no_argument, &basic_mode, true},
        {"no_mem", no_argument, &no_mem, true},
        {"no_normalization", no_argument, &no_normalization, true},
        {"verbose", no_argument, &verbose, true},
        {"cpu", required_argument, 0, 'p'},
        {"usr", required_argument, 0, 'r'},
        {"os", required_argument, 0, 's'},
        {"debug", no_argument, &debug, true},
        {"csv", required_argument,0, 'v'},
        {"name", required_argument, 0, 'N'},
        {"instructions_per_block", required_argument, 0, 'B'},
        {"measurement", required_argument, 0, 'M'},
        {"n_pmc", required_argument, 0, 'P'},
        {"help", no_argument, 0, 'h'},
        {0, 0, 0, 0}
    };

    int option = 0;
    while ((option = getopt_long_only(argc, argv, "", long_opts, NULL)) != -1) {
        switch (option) {
            case 0:
                break;
            case 'c':
                code_path = optarg;
                code_length = mmap_file(optarg, &code);
                break;
            case 'i':
                code_init_length = mmap_file(optarg, &code_init);
                break;
            case 't':
                code_late_init_length = mmap_file(optarg, &code_late_init);
                break;
            case 'o':
                code_one_time_init_length = mmap_file(optarg, &code_one_time_init);
                break;
            case 'f': ;
                config_file_name = optarg;
                break;
            case 'n':
                n_measurements = atol(optarg);
                break;
            case 'u':
                unroll_count = atol(optarg);
                if (unroll_count <= 0) {
                    fprintf(stderr, "Error: unroll_count must be > 0\n");
                    return 1;
                }
                break;
            case 'l':
                loop_count = atol(optarg);
                break;
            case 'w':
                warm_up_count = atol(optarg);
                break;
            case 'a':
                initial_warm_up_count = atol(optarg);
                break;
            case 'm':
                alignment_offset = (size_t)atol(optarg);
                break;
            case 'p':
                cpu = atol(optarg);
                break;
            case 'r':
                usr = atoi(optarg);
                break;
            case 's':
                os = atoi(optarg);
                break;
            case 'v':
                csv_path = optarg;
                break;
            case 'N':
                benchmark_name = optarg;
                break;
            case 'B':
                instructions_per_block = strtol(optarg, NULL, 10);

                if (instructions_per_block <= 0) {
                    print_error("-instructions_per_block must be greater than zero");
                    return 1;
                }

                break;

            case 'M':
                measurement_name = optarg;
                break;
            case 'P':
                n_pmc_override = atoi(optarg);
                break;
            default:
                print_usage();
                return 1;
            }
    }

    switch (aggregate_function) {
    case AVG_20_80:
        aggregate_name = "average";
        break;
    case MED:
        aggregate_name = "median";
        break;
    case MIN:
        aggregate_name = "minimum";
        break;
    case MAX:
        aggregate_name = "maximum";
        break;
    default:
        aggregate_name = "unknown";
        break;
    }

    #if defined(__riscv)

    if (drain_frontend) {
        print_error("RISC-V backend does not support -df yet");
        return 1;
    }

    if (debug) {
        print_error("RISC-V backend does not support -debug yet");
        return 1;
    }

    if (no_mem) {
        print_error("RISC-V backend does not support -no_mem yet");
        return 1;
    }

    #endif

    /*************************************
     * Check CPUID and parse config file
     ************************************/
    if (check_cpuid()) {
        return 1;
    }

    if (n_pmc_override > 0) {
        n_programmable_counters = n_pmc_override;
    }

    if (config_file_name) {
        char* config_mmap;
        size_t len = mmap_file(config_file_name, &config_mmap);
        pfc_config_file_content = calloc(len+1, sizeof(char));
        memcpy(pfc_config_file_content, config_mmap, len);
        parse_counter_configs();
    }

    /*************************************
     * Pin thread to CPU
     ************************************/
    if (cpu == -1) {
        cpu = sched_getcpu();
    }

    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cpu, &mask);

    if (sched_setaffinity(0, sizeof(cpu_set_t), &mask) == -1) {
        fprintf(stderr, "Error: Could not pin thread to core %d\n", cpu);
        return 1;
    }
    
    if (csv_path != NULL) {
        csv_file = open_csv_file(csv_path);

        if (csv_file == NULL) {
            return 1;
        }
    }

    #if defined(__riscv)

    // if (!riscv_pmu_open_raw(&test_counter, 0x34, cpu, usr, os)) {
    //     print_error("Could not open X100 alu_inst event");
    //     return 1;
    // }

    // test_counter_open = true;

    // printf("raw selector       : 0x%llx\n", (unsigned long long)test_counter.selector);
    // printf("perf mmap index    : %u\n", test_counter.perf_index);
    // printf("hardware index     : %u\n", test_counter.hardware_index);
    // printf("probable CSR       : hpmcounter%u\n", test_counter.hardware_index);
    // printf("counter width      : %u\n", test_counter.width);

    // const unsigned int csr = 0xC00U + test_counter.hardware_index;
    // riscv_pmc_csr_number = csr;

    // const uint32_t csrr_t0 = encode_csrr(5, csr);
    // printf("CSR number         : 0x%x\n", csr);
    // printf("csrr t0 encoding   : 0x%08x\n", csrr_t0);

    // riscv_pmu_close(&test_counter);

    #endif


    /*************************************
     * Allocate memory
     ************************************/
    size_t runtime_code_length = get_required_runtime_code_length();
    posix_memalign((void**)&runtime_code, sysconf(_SC_PAGESIZE), runtime_code_length);
    if (!runtime_code) {
        fprintf(stderr, "Error: Failed to allocate memory for runtime_code\n");
        return 1;
    }
    if (mprotect(runtime_code, runtime_code_length, (PROT_READ | PROT_WRITE |PROT_EXEC))) {
        fprintf(stderr, "Error: mprotect failed\n");
        return 1;
    }

    size_t runtime_one_time_init_code_length = code_one_time_init_length + 10000;
    posix_memalign((void**)&runtime_one_time_init_code, sysconf(_SC_PAGESIZE), runtime_one_time_init_code_length);
    if (!runtime_one_time_init_code) {
        fprintf(stderr, "Error: Failed to allocate memory for runtime_one_time_init_code\n");
        return 1;
    }
    if (mprotect(runtime_one_time_init_code, runtime_one_time_init_code_length, (PROT_READ | PROT_WRITE |PROT_EXEC))) {
        fprintf(stderr, "Error: mprotect failed\n");
        return 1;
    }

    posix_memalign((void**)&runtime_r14, sysconf(_SC_PAGESIZE), RUNTIME_R_SIZE);
    posix_memalign((void**)&runtime_rbp, sysconf(_SC_PAGESIZE), RUNTIME_R_SIZE);
    posix_memalign((void**)&runtime_rdi, sysconf(_SC_PAGESIZE), RUNTIME_R_SIZE);
    posix_memalign((void**)&runtime_rsi, sysconf(_SC_PAGESIZE), RUNTIME_R_SIZE);
    posix_memalign((void**)&runtime_rsp, sysconf(_SC_PAGESIZE), RUNTIME_R_SIZE);
    if (!runtime_r14 || !runtime_rbp || !runtime_rdi || !runtime_rsi || !runtime_rsp) {
        fprintf(stderr, "Error: Could not allocate memory for runtime_r*\n");
        return 1;
    }
    memset(runtime_r14, 0, RUNTIME_R_SIZE);
    memset(runtime_rbp, 0, RUNTIME_R_SIZE);
    memset(runtime_rdi, 0, RUNTIME_R_SIZE);
    memset(runtime_rsi, 0, RUNTIME_R_SIZE);
    memset(runtime_rsp, 0, RUNTIME_R_SIZE);
    // runtime_r14 += RUNTIME_R_SIZE/2;
    // runtime_rbp += RUNTIME_R_SIZE/2;
    // runtime_rdi += RUNTIME_R_SIZE/2;
    // runtime_rsi += RUNTIME_R_SIZE/2;
    // runtime_rsp += RUNTIME_R_SIZE/2;
    runtime_r14 = (char *)runtime_r14 + RUNTIME_R_SIZE / 2;
    runtime_rbp = (char *)runtime_rbp + RUNTIME_R_SIZE / 2;
    runtime_rdi = (char *)runtime_rdi + RUNTIME_R_SIZE / 2;
    runtime_rsi = (char *)runtime_rsi + RUNTIME_R_SIZE / 2;
    runtime_rsp = (char *)runtime_rsp + RUNTIME_R_SIZE / 2;

    for (int i=0; i<MAX_PROGRAMMABLE_COUNTERS; i++) {
        measurement_results[i] = malloc(n_measurements*sizeof(int64_t));
        measurement_results_base[i] = malloc(n_measurements*sizeof(int64_t));
        if (!measurement_results[i] || !measurement_results_base[i]) {
            fprintf(stderr, "Error: Could not allocate memory for measurement_results\n");
            return 1;
        }
    }

    clear_perf_counter_configurations();
    clear_perf_counters();
    clear_overflow_status_bits();
    enable_perf_ctrs_globally();

    long base_unroll_count = (basic_mode?0:unroll_count);
    long main_unroll_count = (basic_mode?unroll_count:2*unroll_count);
    long base_loop_count = (basic_mode?0:loop_count);
    long main_loop_count = loop_count;

    char buf[100];
    char* measurement_template;

    create_and_run_one_time_init_code();
    run_initial_warmup_experiment();

    /*************************************
     * Fixed-function counters
     ************************************/
    // if (use_fixed_counters) {
    //     if (is_AMD_CPU) {
    //         if (no_mem) {
    //             measurement_template = (char*)&measurement_RDTSC_template_noMem;
    //         } else {
    //             measurement_template = (char*)&measurement_RDTSC_template;
    //         }
    //     } else {
    //         if (no_mem) {
    //             measurement_template = (char*)&measurement_FF_template_Intel_noMem;
    //         } else {
    //             measurement_template = (char*)&measurement_FF_template_Intel;
    //         }
    //     }

    //     if (is_AMD_CPU) {
    //         run_experiment(measurement_template, measurement_results_base, 1, base_unroll_count, base_loop_count);
    //         run_experiment(measurement_template, measurement_results, 1, main_unroll_count, main_loop_count);

    //         if (verbose) {
    //             printf("\nRDTSC results (unroll_count=%ld, loop_count=%ld):\n\n", base_unroll_count, base_loop_count);
    //             print_all_measurement_results(measurement_results_base, 1);
    //             printf("RDTSC results (unroll_count=%ld, loop_count=%ld):\n\n", main_unroll_count, main_loop_count);
    //             print_all_measurement_results(measurement_results, 1);
    //         }

    //         printf("%s", compute_result_str(buf, sizeof(buf), "RDTSC", 0));
    //     } else {
    //         configure_perf_ctrs_FF_Intel(usr, os);

    //         run_experiment(measurement_template, measurement_results_base, 4, base_unroll_count, base_loop_count);
    //         run_experiment(measurement_template, measurement_results, 4, main_unroll_count, main_loop_count);

    //         if (verbose) {
    //             printf("\nRDTSC and fixed-function counter results (unroll_count=%ld, loop_count=%ld):\n\n", base_unroll_count, base_loop_count);
    //             print_all_measurement_results(measurement_results_base, 4);
    //             printf("RDTSC and fixed-function counter results (unroll_count=%ld, loop_count=%ld):\n\n", main_unroll_count, main_loop_count);
    //             print_all_measurement_results(measurement_results, 4);
    //         }

    //         printf("%s", compute_result_str(buf, sizeof(buf), "RDTSC", 0));
    //         printf("%s", compute_result_str(buf, sizeof(buf), "Instructions retired", 1));
    //         printf("%s", compute_result_str(buf, sizeof(buf), "Core cycles", 2));
    //         printf("%s", compute_result_str(buf, sizeof(buf), "Reference cycles", 3));
    //     }
    // }

    if (use_fixed_counters) {
    #if defined(__riscv)
        // RISC-V: cycles/instret are read together with the raw events (run_riscv_measurements)

    #elif defined(__x86_64__) || defined(__i386__)
        if (is_AMD_CPU) {
            measurement_template = no_mem ? (char *)&measurement_RDTSC_template_noMem
                                        : (char *)&measurement_RDTSC_template;
        } else {
            measurement_template = no_mem ? (char *)&measurement_FF_template_Intel_noMem
                                        : (char *)&measurement_FF_template_Intel;
        }

        if (is_AMD_CPU) {
            run_experiment(measurement_template, measurement_results_base, 1, base_unroll_count, base_loop_count);
            run_experiment(measurement_template, measurement_results, 1, main_unroll_count, main_loop_count);

            if (verbose) {
                printf("\nRDTSC results (unroll_count=%ld, loop_count=%ld):\n\n", base_unroll_count, base_loop_count);
                print_all_measurement_results(measurement_results_base, 1);
                printf("RDTSC results (unroll_count=%ld, loop_count=%ld):\n\n", main_unroll_count, main_loop_count);
                print_all_measurement_results(measurement_results, 1);
            }

            printf("%s", compute_result_str(buf, sizeof(buf), "RDTSC", 0));
        } else {
            configure_perf_ctrs_FF_Intel(usr, os);
            run_experiment(measurement_template, measurement_results_base, 4, base_unroll_count, base_loop_count);
            run_experiment(measurement_template, measurement_results, 4, main_unroll_count, main_loop_count);

            if (verbose) {
                printf("\nRDTSC and fixed-function counter results (unroll_count=%ld, loop_count=%ld):\n\n", base_unroll_count, base_loop_count);
                print_all_measurement_results(measurement_results_base, 4);
                printf("RDTSC and fixed-function counter results (unroll_count=%ld, loop_count=%ld):\n\n", main_unroll_count, main_loop_count);
                print_all_measurement_results(measurement_results, 4);
            }

            printf("%s", compute_result_str(buf, sizeof(buf), "RDTSC", 0));
            printf("%s", compute_result_str(buf, sizeof(buf), "Instructions retired", 1));
            printf("%s", compute_result_str(buf, sizeof(buf), "Core cycles", 2));
            printf("%s", compute_result_str(buf, sizeof(buf), "Reference cycles", 3));
        }
    #else
    #error "Unsupported architecture"
    #endif
    }

    /*************************************
     * Programmable counters
     ************************************/
    // int n_used_counters = n_programmable_counters;
    // if (is_AMD_CPU) {
    //     if (no_mem) {
    //         measurement_template = (char*)&measurement_template_AMD_noMem;
    //     } else {
    //         measurement_template = (char*)&measurement_template_AMD;
    //     }
    // } else {
    //     if (n_used_counters >= 4) {
    //         n_used_counters = 4;
    //         if (no_mem) {
    //              measurement_template = (char*)&measurement_template_Intel_noMem_4;
    //         } else {
    //             measurement_template = (char*)&measurement_template_Intel_4;
    //         }
    //     } else {
    //         n_used_counters = 2;
    //         if (no_mem) {
    //             measurement_template = (char*)&measurement_template_Intel_noMem_2;
    //         } else {
    //             measurement_template = (char*)&measurement_template_Intel_2;
    //         }
    //     }
    // }

    int n_used_counters = 0;

    #if defined(__riscv)

    n_used_counters = n_programmable_counters;

    /*
    * measurement_results[] and pfc_mem[] currently have
    * MAX_PROGRAMMABLE_COUNTERS entries.
    */
    if (n_used_counters > MAX_PROGRAMMABLE_COUNTERS) {
        n_used_counters = MAX_PROGRAMMABLE_COUNTERS;
    }

    if (n_used_counters < 1) {
        print_error("No programmable PMU counters are available");

        return 1;
    }

    if (no_mem) {
        measurement_template = (char *)&measurement_template_RISCV_noMem;
    } else {
        measurement_template = (char *)&measurement_template_RISCV;
    }

    #elif defined(__x86_64__) || defined(__i386__)

    n_used_counters = n_programmable_counters;

    if (is_AMD_CPU) {
        if (no_mem) {
            measurement_template = (char *)&measurement_template_AMD_noMem;
        } else {
            measurement_template = (char *)&measurement_template_AMD;
        }
    } else {
        if (n_used_counters >= 4) {
            n_used_counters = 4;

            if (no_mem) {
                measurement_template = (char *)&measurement_template_Intel_noMem_4;
            } else {
                measurement_template = (char *)&measurement_template_Intel_4;
            }
        } else {
            n_used_counters = 2;

            if (no_mem) {
                measurement_template = (char *)&measurement_template_Intel_noMem_2;
            } else {
                measurement_template = (char *)&measurement_template_Intel_2;
            }
        }
    }

    #else
    #error "Unsupported architecture"
    #endif

    // size_t next_pfc_config = 0;
    // while (next_pfc_config < n_pfc_configs) {
    //     char* pfc_descriptions[MAX_PROGRAMMABLE_COUNTERS] = {0};
    //     next_pfc_config = configure_perf_ctrs_programmable(next_pfc_config, usr, os, n_used_counters, 0, pfc_descriptions);

    //     run_experiment(measurement_template, measurement_results_base, n_used_counters, base_unroll_count, base_loop_count);
    //     run_experiment(measurement_template, measurement_results, n_used_counters, main_unroll_count, main_loop_count);

    //     if (verbose) {
    //         printf("\nProgrammable counter results (unroll_count=%ld, loop_count=%ld):\n\n", base_unroll_count, base_loop_count);
    //         print_all_measurement_results(measurement_results_base, n_used_counters);
    //         printf("Programmable counter results (unroll_count=%ld, loop_count=%ld):\n\n", main_unroll_count, main_loop_count);
    //         print_all_measurement_results(measurement_results, n_used_counters);
    //     }

    //     for (size_t c=0; c < n_used_counters; c++) {
    //         if (pfc_descriptions[c]) printf("%s", compute_result_str(buf, sizeof(buf), pfc_descriptions[c], c));
    //     }
    // }

    #if defined(__riscv)

    if (run_riscv_measurements(csv_file, cpu, usr, os, code_path, code_length, benchmark_name,
                               measurement_name, aggregate_name, instructions_per_block,
                               base_unroll_count, main_unroll_count, base_loop_count, main_loop_count) != 0) {
        return 1;
    }

    #elif defined(__x86_64__) || defined(__i386__)
    size_t next_pfc_config = 0;
    
    while (next_pfc_config < n_pfc_configs) {
        char *pfc_descriptions[MAX_PROGRAMMABLE_COUNTERS] = {0};
        next_pfc_config = configure_perf_ctrs_programmable(next_pfc_config, usr, os, n_used_counters, 0, pfc_descriptions);

        run_experiment(measurement_template, measurement_results_base, n_used_counters, base_unroll_count, base_loop_count);
        run_experiment(measurement_template, measurement_results, n_used_counters, main_unroll_count, main_loop_count);

        if (verbose) {
            printf("\nProgrammable counter results (unroll_count=%ld, loop_count=%ld):\n\n", base_unroll_count, base_loop_count);
            print_all_measurement_results(measurement_results_base, n_used_counters);
            printf("Programmable counter results (unroll_count=%ld, loop_count=%ld):\n\n", main_unroll_count, main_loop_count);
            print_all_measurement_results(measurement_results, n_used_counters);
        }

        for (size_t c = 0; c < (size_t)n_used_counters; ++c) {
            if (pfc_descriptions[c] != NULL) {
                printf("%s", compute_result_str(buf, sizeof(buf), pfc_descriptions[c], c));
            }
        }
    }
    #else
    #error "Unsupported architecture"
    #endif

    // #if defined(__riscv)
    // if (test_counter_open) {
    //     riscv_pmu_close(&test_counter);
    // }
    // #endif

    /*************************************
     * Cleanup
     ************************************/

     if (csv_file != NULL) {
        if (fclose(csv_file) != 0) {
            perror("fclose CSV");
            return 1;
        }

        csv_file = NULL;
    }

     #if defined(__riscv)
    for (size_t i = 0; i < n_pfc_configs; ++i) {
        free(pfc_configs[i].description);
        pfc_configs[i].description = NULL;
    }
    #endif

    free(runtime_code);
    free(runtime_one_time_init_code);
    free(runtime_r14 - RUNTIME_R_SIZE/2);
    free(runtime_rbp - RUNTIME_R_SIZE/2);
    free(runtime_rdi - RUNTIME_R_SIZE/2);
    free(runtime_rsi - RUNTIME_R_SIZE/2);
    free(runtime_rsp - RUNTIME_R_SIZE/2);

    for (int i=0; i<MAX_PROGRAMMABLE_COUNTERS; i++) {
        free(measurement_results[i]);
        free(measurement_results_base[i]);
    }

    if (pfc_config_file_content) {
        free(pfc_config_file_content);
    }

    return 0;
}
