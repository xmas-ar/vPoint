# Makefile for compiling xdp_forwarding.c with clang and full kernel headers

CLANG ?= clang
KERN_VERSION := $(shell uname -r)
KERNEL_SRC ?= /home/xmas/rpmbuild/SOURCES/linux-$(KERN_VERSION)
BPF_HEADERS_PARENT_DIR ?= /usr/include # Changed variable name and path

# Rutas necesarias para incluir headers internos como rwonce.h
CFLAGS = -O2 -Wall \
    -target bpf \
    -D__TARGET_ARCH_$(shell uname -m | sed 's/x86_64/x86/') \
    -I. \
    -I$(KERNEL_SRC)/include \
    -I$(KERNEL_SRC)/arch/x86/include \
    -I$(KERNEL_SRC)/arch/x86/include/generated \
    -I$(KERNEL_SRC)/include/generated \
    -I$(KERNEL_SRC)/include/uapi \
    -I$(KERNEL_SRC)/include/generated/uapi \
    -I$(KERNEL_SRC)/arch/x86/include/uapi \
    -I$(BPF_HEADERS_PARENT_DIR) \
    -D__KERNEL__ \
    -Wno-unused-value \
    -Wno-pointer-sign \
    -Wno-compare-distinct-pointer-types \
    -Wno-gnu-variable-sized-type-not-at-end \
    -Wno-address-of-packed-member \
    -Wno-tautological-compare \
    -g

SRC = xdp_forwarding.c
OUT = xdp_forwarding.o

all: $(OUT)

$(OUT): $(SRC) forwarding_maps.bpf.h
	$(CLANG) $(CFLAGS) -c $(SRC) -o $(OUT)

clean:
	rm -f $(OUT)
