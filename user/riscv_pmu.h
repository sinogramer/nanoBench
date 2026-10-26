#ifndef RISCV_PMU_H
#define RISCV_PMU_H

#include <linux/perf_event.h>
#include <stdbool.h>
#include <stdint.h>

struct riscv_pmu_counter {
    int fd;
    struct perf_event_mmap_page *page;
    uint64_t selector;
    uint32_t perf_index;
    uint32_t hardware_index;
    uint16_t width;
};

bool riscv_pmu_open_raw(struct riscv_pmu_counter *counter, uint64_t selector, int cpu, bool usr, bool os);
void riscv_pmu_close(struct riscv_pmu_counter *counter);

#endif