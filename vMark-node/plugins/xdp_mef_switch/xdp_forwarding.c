#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/if_vlan.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>
#include "forwarding_maps.bpf.h" // Contiene TAG_TYPE_CVLAN, TAG_TYPE_SVLAN, etc.

#ifndef __VLAN_HDR_DEF
#define __VLAN_HDR_DEF
struct vlan_hdr {
    __be16 h_vlan_TCI;
    __be16 h_vlan_encapsulated_proto;
};
#endif

char _license[] SEC("license") = "GPL";

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 4096); // O el valor que necesites
    __type(key, struct forwarding_key);
    __type(value, struct forwarding_value);
} fw_table SEC(".maps");

static __always_inline int parse_eth_vlan(void *data, void *data_end, struct forwarding_key *key) {
    struct ethhdr *eth = data;
    __u16 current_eth_proto = eth->h_proto;
    void *current_offset = (void *)(eth + 1);

    key->vlan_id = 0;
    key->svlan_id = 0;

    if (current_eth_proto == bpf_htons(ETH_P_8021AD)) {
        struct vlan_hdr *vhdr_s = current_offset;
        if ((void*)(vhdr_s + 1) > data_end)
            return XDP_ABORTED;
        key->svlan_id = bpf_ntohs(vhdr_s->h_vlan_TCI) & 0x0FFF;
        current_eth_proto = vhdr_s->h_vlan_encapsulated_proto;
        current_offset = (void *)(vhdr_s + 1);

        if (current_eth_proto == bpf_htons(ETH_P_8021Q)) {
            struct vlan_hdr *vhdr_c = current_offset;
            if ((void*)(vhdr_c + 1) > data_end)
                return XDP_ABORTED;
            key->vlan_id = bpf_ntohs(vhdr_c->h_vlan_TCI) & 0x0FFF;
        }
    } else if (current_eth_proto == bpf_htons(ETH_P_8021Q)) {
        struct vlan_hdr *vhdr_c = current_offset;
        if ((void*)(vhdr_c + 1) > data_end)
            return XDP_ABORTED;
        key->vlan_id = bpf_ntohs(vhdr_c->h_vlan_TCI) & 0x0FFF;
    }

    return 0;
}

SEC("xdp")
int xdp_program(struct xdp_md *ctx) {
    void *data = (void *)(long)ctx->data;
    void *data_end = (void *)(long)ctx->data_end;
    struct ethhdr *eth = data;

    if ((void *)(eth + 1) > data_end)
        return XDP_PASS;

    struct forwarding_key key = {};
    key.ingress_ifindex = ctx->ingress_ifindex;
    if (parse_eth_vlan(data, data_end, &key) < 0) {
        bpf_printk("XDP: parse_eth_vlan failed.\n");
    } else {
        bpf_printk("XDP: parse_eth_vlan succeeded. VLAN ID: %u, SVLAN ID: %u\n", key.vlan_id, key.svlan_id);
    }

    struct forwarding_value *fwd_val = bpf_map_lookup_elem(&fw_table, &key);
    if (!fwd_val) {
        bpf_printk("XDP: No rule found for key. Passing.\n");
        return XDP_PASS;
    }

    for (int i = 0; i < MAX_ACTIONS; i++) {
        if (i >= fwd_val->num_actions)
            break;

        struct action_step *step = &fwd_val->steps[i];
        data = (void *)(long)ctx->data;
        data_end = (void *)(long)ctx->data_end;
        eth = data;

        if ((void *)(eth + 1) > data_end) {
            bpf_printk("XDP: Packet too short for ethhdr before action type %u.\n", step->type);
            return XDP_ABORTED;
        }

        switch (step->type) {
            case ACTION_TYPE_PUSH: {
                __be16 original_eth_proto = eth->h_proto; // Capturado del encabezado eth original antes de adjust_head
                unsigned char original_dmac[ETH_ALEN];
                unsigned char original_smac[ETH_ALEN];

                // Copia las MACs originales a variables locales ANTES de adjust_head
                __builtin_memcpy(original_dmac, eth->h_dest, ETH_ALEN);
                __builtin_memcpy(original_smac, eth->h_source, ETH_ALEN);

                // Para depuración: Imprime las MACs de 'eth' *antes* de cualquier ajuste
                bpf_printk("XDP_PROGRAM PUSH (PRE-ADJUST): src=%02x:%02x:%02x:%02x:%02x:%02x\n",
                    eth->h_source[0], eth->h_source[1], eth->h_source[2], eth->h_source[3], eth->h_source[4], eth->h_source[5]);
                bpf_printk("XDP_PROGRAM PUSH (PRE-ADJUST): dst=%02x:%02x:%02x:%02x:%02x:%02x proto=0x%04x\n",
                    eth->h_dest[0], eth->h_dest[1], eth->h_dest[2], eth->h_dest[3], eth->h_dest[4], eth->h_dest[5], bpf_ntohs(eth->h_proto));

                if (bpf_xdp_adjust_head(ctx, (int)(sizeof(struct vlan_hdr)) * -1)) {
                    bpf_printk("XDP_PROGRAM PUSH: bpf_xdp_adjust_head FAILED\n");
                    return XDP_ABORTED;
                }

                void *data_new_push = (void *)(long)ctx->data;
                void *data_end_new_push = (void *)(long)ctx->data_end;
                struct ethhdr *eth_new_push = data_new_push; // Apunta al nuevo espacio al inicio

                // Ubicación del contenido del encabezado Ethernet original después del desplazamiento (para depuración)
                struct ethhdr *original_eth_content_shifted = (struct ethhdr *)((void *)eth_new_push + sizeof(struct vlan_hdr));

                // Comprobaciones de límites
                if ((void*)(eth_new_push + 1) > data_end_new_push) {
                    bpf_printk("XDP_PROGRAM PUSH: Paquete demasiado corto para nuevo ethhdr.\n");
                    return XDP_ABORTED;
                }
                struct vlan_hdr *vlan_new_push = (struct vlan_hdr *)(eth_new_push + 1);
                if ((void*)(vlan_new_push + 1) > data_end_new_push) {
                    bpf_printk("XDP_PROGRAM PUSH: Paquete demasiado corto para nuevo vlanhdr.\n");
                    return XDP_ABORTED;
                }
                if ((void*)(original_eth_content_shifted + 1) > data_end_new_push) { // Comprobación para el puntero de depuración
                     bpf_printk("XDP_PROGRAM PUSH: Comprobación de límites fallida para original_eth_content_shifted.\n");
                     return XDP_ABORTED;
                }
                
                // Imprime el contenido desplazado para depuración (opcional, ya que no lo usamos para la copia)
                bpf_printk("XDP_PROGRAM PUSH (SHIFTED_CONTENT): src=%02x:%02x:%02x:%02x:%02x:%02x\n",
                    original_eth_content_shifted->h_source[0], original_eth_content_shifted->h_source[1], original_eth_content_shifted->h_source[2], original_eth_content_shifted->h_source[3], original_eth_content_shifted->h_source[4], original_eth_content_shifted->h_source[5]);
                bpf_printk("XDP_PROGRAM PUSH (SHIFTED_CONTENT): dst=%02x:%02x:%02x:%02x:%02x:%02x proto=0x%04x\n",
                    original_eth_content_shifted->h_dest[0], original_eth_content_shifted->h_dest[1], original_eth_content_shifted->h_dest[2], original_eth_content_shifted->h_dest[3], original_eth_content_shifted->h_dest[4], original_eth_content_shifted->h_dest[5], bpf_ntohs(original_eth_content_shifted->h_proto));

                // Construye el nuevo encabezado Ethernet en eth_new_push
                // Copia las MACs desde las variables locales guardadas
                __builtin_memcpy(eth_new_push->h_dest, original_dmac, ETH_ALEN);
                __builtin_memcpy(eth_new_push->h_source, original_smac, ETH_ALEN);

                if (step->tag_type == TAG_TYPE_CVLAN) {
                    eth_new_push->h_proto = bpf_htons(ETH_P_8021Q);
                } else if (step->tag_type == TAG_TYPE_SVLAN) {
                    eth_new_push->h_proto = bpf_htons(ETH_P_8021AD);
                } else {
                    bpf_printk("XDP_PROGRAM PUSH: tag_type desconocido %u\n", step->tag_type);
                    return XDP_ABORTED;
                }

                // Rellena el nuevo encabezado VLAN
                vlan_new_push->h_vlan_TCI = bpf_htons(step->vlan_id & 0x0FFF);
                vlan_new_push->h_vlan_encapsulated_proto = original_eth_proto;

                bpf_printk("XDP_PROGRAM PUSH: Reescritura de encabezado completa.\n");

                bpf_printk("XDP_PROGRAM PUSH: AFTER: src=%02x:%02x:%02x:%02x:%02x:%02x\n",
                    eth_new_push->h_source[0], eth_new_push->h_source[1], eth_new_push->h_source[2], eth_new_push->h_source[3], eth_new_push->h_source[4], eth_new_push->h_source[5]);
                bpf_printk("XDP_PROGRAM PUSH: AFTER: dst=%02x:%02x:%02x:%02x:%02x:%02x proto=0x%04x\n",
                    eth_new_push->h_dest[0], eth_new_push->h_dest[1], eth_new_push->h_dest[2], eth_new_push->h_dest[3], eth_new_push->h_dest[4], eth_new_push->h_dest[5], bpf_ntohs(eth_new_push->h_proto));

                break;
            }
            case ACTION_TYPE_POP: {
                __u16 current_eth_proto_pop = eth->h_proto;
                if (current_eth_proto_pop != bpf_htons(ETH_P_8021Q) && current_eth_proto_pop != bpf_htons(ETH_P_8021AD)) {
                    bpf_printk("XDP_PROGRAM POP: No VLAN tag (proto 0x%04x), skipping pop.\n", bpf_ntohs(current_eth_proto_pop));
                    break;
                }

                bpf_printk("XDP_PROGRAM POP: BEFORE: src=%02x:%02x:%02x:%02x:%02x:%02x\n",
                    eth->h_source[0], eth->h_source[1], eth->h_source[2], eth->h_source[3], eth->h_source[4], eth->h_source[5]);
                bpf_printk("XDP_PROGRAM POP: BEFORE: dst=%02x:%02x:%02x:%02x:%02x:%02x proto=0x%04x\n",
                    eth->h_dest[0], eth->h_dest[1], eth->h_dest[2], eth->h_dest[3], eth->h_dest[4], eth->h_dest[5], bpf_ntohs(eth->h_proto));

                unsigned char original_dmac[ETH_ALEN];
                unsigned char original_smac[ETH_ALEN];
                __be16 inner_eth_proto;

                struct vlan_hdr *vlan_header = (struct vlan_hdr *)(eth + 1);
                if ((void*)(vlan_header + 1) > data_end) { // Check against original data_end
                    bpf_printk("XDP_PROGRAM POP: Packet too short for VLAN header access.\n");
                    return XDP_ABORTED;
                }

                __builtin_memcpy(original_dmac, eth->h_dest, ETH_ALEN);
                __builtin_memcpy(original_smac, eth->h_source, ETH_ALEN);
                inner_eth_proto = vlan_header->h_vlan_encapsulated_proto;

                int offset_to_remove = sizeof(struct ethhdr) + sizeof(struct vlan_hdr);
                if (bpf_xdp_adjust_head(ctx, offset_to_remove)) {
                    bpf_printk("XDP_PROGRAM POP: bpf_xdp_adjust_head (remove old headers) FAILED\n");
                    return XDP_ABORTED;
                }

                if (bpf_xdp_adjust_head(ctx, (int)(sizeof(struct ethhdr)) * -1)) {
                    bpf_printk("XDP_PROGRAM POP: bpf_xdp_adjust_head (add new ethhdr) FAILED\n");
                    return XDP_ABORTED;
                }

                void *data_new_pop = (void *)(long)ctx->data;
                void *data_end_new_pop = (void *)(long)ctx->data_end;
                struct ethhdr *eth_new_pop = data_new_pop;

                if ((void*)(eth_new_pop + 1) > data_end_new_pop) {
                    bpf_printk("XDP_PROGRAM POP: Packet too short for new ethhdr after adjust.\n");
                    return XDP_ABORTED;
                }

                __builtin_memcpy(eth_new_pop->h_dest, original_dmac, ETH_ALEN);
                __builtin_memcpy(eth_new_pop->h_source, original_smac, ETH_ALEN);
                eth_new_pop->h_proto = inner_eth_proto;
                
                bpf_printk("XDP_PROGRAM POP: Header rewrite complete.\n");

                bpf_printk("XDP_PROGRAM POP: AFTER: src=%02x:%02x:%02x:%02x:%02x:%02x\n",
                    eth_new_pop->h_source[0], eth_new_pop->h_source[1], eth_new_pop->h_source[2], eth_new_pop->h_source[3], eth_new_pop->h_source[4], eth_new_pop->h_source[5]);
                bpf_printk("XDP_PROGRAM POP: AFTER: dst=%02x:%02x:%02x:%02x:%02x:%02x proto=0x%04x\n",
                    eth_new_pop->h_dest[0], eth_new_pop->h_dest[1], eth_new_pop->h_dest[2], eth_new_pop->h_dest[3], eth_new_pop->h_dest[4], eth_new_pop->h_dest[5], bpf_ntohs(eth_new_pop->h_proto));

                break;
            }
            case ACTION_TYPE_FORWARD: {
                bpf_printk("XDP_PROGRAM FORWARD: Attempting to forward to ifindex %u\n", step->target_ifindex);

                if (step->target_ifindex == 0) {
                    bpf_printk("XDP_PROGRAM FORWARD: Invalid target_ifindex 0. Passing packet.\n");
                    return XDP_PASS;
                }

                int ret = bpf_redirect(step->target_ifindex, 0);
                bpf_printk("XDP_PROGRAM FORWARD: bpf_redirect returned %d\n", ret);
                return ret;
            }
            default:
                bpf_printk("XDP: Unknown action type %u\n", step->type);
                return XDP_ABORTED;
        }
    }

    bpf_printk("XDP: No terminal action in rule. Passing.\n");
    return XDP_PASS;
}