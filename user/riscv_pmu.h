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

/*
 * Event group: several events that are measured in the same run.
 * The first event is the (pinned) group leader, so the kernel puts either all
 * events on hardware counters at the same time or none of them.
 */
#define RISCV_PMU_MAX_EVENTS 24

struct riscv_pmu_event {
    uint32_t type;      /* PERF_TYPE_HARDWARE or PERF_TYPE_RAW */
    uint64_t config;    /* PERF_COUNT_HW_* or raw selector */
};

struct riscv_pmu_group {
    int n;
    struct riscv_pmu_counter ctr[RISCV_PMU_MAX_EVENTS];
    uint32_t lock_snapshot[RISCV_PMU_MAX_EVENTS];   /* page->lock before a run */
};

enum {
    RISCV_PMU_OK = 0,
    RISCV_PMU_OPEN_FAILED = -1,     /* perf_event_open() or mmap() failed */
    RISCV_PMU_NOT_SCHEDULED = -2,   /* opened, but not placed on user-readable counters */
};

int riscv_pmu_group_open(struct riscv_pmu_group *group, const struct riscv_pmu_event *events, int n,
                         int cpu, bool usr, bool os);
void riscv_pmu_group_close(struct riscv_pmu_group *group);

/*
 * The kernel increments page->lock whenever it updates the user page, i.e.
 * whenever it (re)programs the counter (e.g. after a context switch). If the
 * lock changed during a run, the raw CSR values of that run are not
 * comparable and the run has to be repeated.
 */
enum {
    RISCV_PMU_UNCHANGED = 0,        /* run is valid */
    RISCV_PMU_REPROGRAMMED = 1,     /* counters were reprogrammed: repeat the run */
    RISCV_PMU_INDEX_CHANGED = 2,    /* an event moved to another hpmcounter: generated code is stale */
};

void riscv_pmu_group_snapshot(struct riscv_pmu_group *group);
int riscv_pmu_group_check(const struct riscv_pmu_group *group);

#endif