#ifndef __FORWARDING_MAPS_BPF_H__
#define __FORWARDING_MAPS_BPF_H__

#include <linux/types.h>
#include <asm/types.h>
// Version: 0.8.0
// Maximum number of actions that can be encoded in a single rule.
// Adjust based on complexity and memory. 3-4 actions (e.g., push, push, forward) are common.
#define MAX_ACTIONS 5

// Action types (ensure these match definitions in map_utils.py)
#define ACTION_TYPE_FORWARD 1
#define ACTION_TYPE_PUSH    2
#define ACTION_TYPE_POP     3
// Potentially others: SET_VLAN, SWAP_VLAN, etc.

// Tag types for push/pop (ensure these match definitions in map_utils.py)
#define TAG_TYPE_NONE  0 // For actions like 'forward'
#define TAG_TYPE_CVLAN 1
#define TAG_TYPE_SVLAN 2


struct forwarding_key {
    __u32 ingress_ifindex; // Interfaz de entrada
    __u16 vlan_id;          // VLAN outer (from match criteria)
    __u16 svlan_id;         // VLAN inner (from match criteria, 0 if no QinQ match)
    __u8 bmac[6];           // B-MAC para PBB (si no se usa, todo 0s)
    __u8 pad[2];          // Padding para alinear a 16 bytes
};

struct action_step {
    __u8 type;          // e.g., ACTION_TYPE_FORWARD, ACTION_TYPE_PUSH, ACTION_TYPE_POP
    __u8 tag_type;      // e.g., TAG_TYPE_CVLAN, TAG_TYPE_SVLAN (for push/pop)
    __u16 vlan_id;      // VLAN ID for push operations
    __u32 target_ifindex; // Egress ifindex for ACTION_TYPE_FORWARD
} __attribute__((packed));

struct forwarding_value {
    __u8 num_actions;                   // 1 byte
    struct action_step steps[5];        // 5 * 8 = 40 bytes
    __u8 pad[9];                        // 9 bytes
}; // Total: 1 + 40 + 9 = 50 bytes


#endif /* __FORWARDING_MAPS_BPF_H__ */