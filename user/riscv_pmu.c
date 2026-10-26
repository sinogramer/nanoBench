#define _GNU_SOURCE

#include "riscv_pmu.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <sched.h>

static int perf_event_open(struct perf_event_attr *attr, pid_t pid, int cpu, int group_fd, unsigned long flags)
{
    return syscall(SYS_perf_event_open, attr, pid, cpu, group_fd, flags);
}

static bool read_counter_metadata(struct riscv_pmu_counter *counter)
{
    for (int attempt = 0; attempt < 10000; ++attempt) {
        uint32_t perf_index;
        uint16_t width;
        uint8_t user_access;

        for (;;) {
            uint32_t begin = __atomic_load_n(&counter->page->lock, __ATOMIC_ACQUIRE);

            if ((begin & 1U) != 0U) {
                continue;
            }

            perf_index = counter->page->index;
            width = counter->page->pmc_width;
            user_access = counter->page->cap_user_rdpmc;

            __atomic_thread_fence(__ATOMIC_ACQUIRE);

            uint32_t end = __atomic_load_n(&counter->page->lock, __ATOMIC_RELAXED);

            if (begin == end) {
                break;
            }
        }

        counter->perf_index = perf_index;
        counter->width = width;

        if (perf_index != 0 && user_access != 0) {
            counter->hardware_index = perf_index - 1;
            return true;
        }

        __asm__ volatile("" ::: "memory");
    }

    return false;
}

static void run_assignment_workload(void)
{
    register uint64_t value = 1;

    for (uint64_t i = 0; i < 100000; ++i) {
        value += i;
        __asm__ volatile("" : "+r"(value));
    }

    __asm__ volatile("" :: "r"(value) : "memory");
}

bool riscv_pmu_open_raw(struct riscv_pmu_counter *counter, uint64_t selector, int cpu, bool usr, bool os)
{
    memset(counter, 0, sizeof(*counter));
    counter->fd = -1;
    counter->selector = selector;

    struct perf_event_attr attr;
    memset(&attr, 0, sizeof(attr));

    attr.type = PERF_TYPE_RAW;
    attr.size = sizeof(attr);
    attr.config = selector;
    attr.disabled = 1;
    attr.pinned = 0;
    attr.exclude_user = !usr;
    attr.exclude_kernel = !os;
    attr.exclude_hv = 1;

    counter->fd = perf_event_open(&attr, 0, cpu, -1, 0);

    if (counter->fd < 0) {
        fprintf(stderr, "perf_event_open(0x%llx): %s\n", (unsigned long long)selector, strerror(errno));
        return false;
    }

    long page_size = sysconf(_SC_PAGESIZE);

    counter->page = mmap(NULL, page_size, PROT_READ, MAP_SHARED, counter->fd, 0);

    fprintf(stderr, "requested CPU: %d, current CPU: %d\n", cpu, sched_getcpu());

    if (counter->page == MAP_FAILED) {
        fprintf(stderr, "mmap PMU metadata: %s\n", strerror(errno));
        counter->page = NULL;
        riscv_pmu_close(counter);
        return false;
    }

    if (ioctl(counter->fd, PERF_EVENT_IOC_RESET, 0) != 0) {
        fprintf(stderr, "PERF_EVENT_IOC_RESET: %s\n", strerror(errno));
        riscv_pmu_close(counter);
        return false;
    }

    if (ioctl(counter->fd, PERF_EVENT_IOC_ENABLE, 0) != 0) {
        fprintf(stderr, "PERF_EVENT_IOC_ENABLE: %s\n", strerror(errno));
        riscv_pmu_close(counter);
        return false;
    }

    run_assignment_workload();

    if (!read_counter_metadata(counter)) {
        fprintf(stderr, "raw event 0x%llx was not scheduled\n", (unsigned long long)selector);
        fprintf(stderr, "  mmap index     : %u\n", counter->page->index);
        fprintf(stderr, "  pmc width      : %u\n", counter->page->pmc_width);
        fprintf(stderr, "  cap_user_rdpmc : %u\n", counter->page->cap_user_rdpmc);
        fprintf(stderr, "  time enabled   : %llu\n", (unsigned long long)counter->page->time_enabled);
        fprintf(stderr, "  time running   : %llu\n", (unsigned long long)counter->page->time_running);
        riscv_pmu_close(counter);
        return false;
    }

    if (counter->hardware_index < 3 || counter->hardware_index > 31) {
        fprintf(stderr, "invalid RISC-V HPM counter index: %u\n", counter->hardware_index);
        riscv_pmu_close(counter);
        return false;
    }

    return true;
}

void riscv_pmu_close(struct riscv_pmu_counter *counter)
{
    if (counter->fd >= 0) {
        ioctl(counter->fd, PERF_EVENT_IOC_DISABLE, 0);
    }

    if (counter->page != NULL) {
        long page_size = sysconf(_SC_PAGESIZE);
        munmap(counter->page, page_size);
        counter->page = NULL;
    }

    if (counter->fd >= 0) {
        close(counter->fd);
        counter->fd = -1;
    }
}