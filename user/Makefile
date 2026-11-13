CC ?= gcc
ARCH ?= $(shell uname -m)

CFLAGS += -O2 -Wall -Wextra
LDFLAGS ?=

OBJS = nanoBench_main.o nanoBench.o

ifeq ($(ARCH),riscv64)
CFLAGS += -DNB_ARCH_RISCV64
OBJS += riscv_pmu.o
endif

nanoBench: $(OBJS)
	$(CC) $(LDFLAGS) -o $@ $(OBJS)

# nanoBench_main.c includes riscv_pmu.h on RISC-V; a change of a struct in it
# must rebuild nanoBench_main.o as well, otherwise the two objects disagree on
# the struct layout.
nanoBench_main.o: nanoBench_main.c ../common/nanoBench.h riscv_pmu.h
	$(CC) $(CFLAGS) -c nanoBench_main.c -o $@

nanoBench.o: ../common/nanoBench.c ../common/nanoBench.h
	$(CC) $(CFLAGS) -c ../common/nanoBench.c -o $@

riscv_pmu.o: riscv_pmu.c riscv_pmu.h
	$(CC) $(CFLAGS) -c riscv_pmu.c -o $@

clean:
	rm -f nanoBench $(OBJS)

.PHONY: clean