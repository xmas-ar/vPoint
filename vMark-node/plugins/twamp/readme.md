# onyx-TWAMP Plugin for vMark-node

This plugin implements a TWAMP (Two-Way Active Measurement Protocol) client and server based on RFC 5357.

## Features

* TWAMP sender and responder mode
* Support for both IPv4 and IPv6
* Configurable parameters:
  - Packet count (1-9999)
  - Packet interval (10-1000ms)
  - Packet padding (0-9000 bytes)
  - ToS/DSCP marking (0-63)
  - TTL value (1-255)
  - Do-not-fragment flag (IPv4 only)
* Detailed performance metrics:
  - Round-trip delay
  - One-way delays (outbound/inbound)
  - Jitter measurements
  - Packet loss tracking
  - Packet counters (Tx/Rx)

## CLI Usage Examples

Start a TWAMP responder:
```bash
twamp ipv4 responder port 5000
twamp ipv6 responder port 5000 padding 1000 ttl 64
```

Start a TWAMP sender:
```bash
twamp ipv4 sender destination-ip 192.168.1.1 port 5000
twamp ipv6 sender destination-ip 2001:db8::1 port 5000 count 100 interval 100
```

Display DSCP mapping table:
```bash
twamp dscptable
```

### Parameter Reference

| Parameter       | Description                | Range/Format     | Required |
|----------------|----------------------------|------------------|----------|
| destination-ip | Target IP address          | IPv4 or IPv6     | Yes (sender) |
| port          | UDP port number            | 1024-65535       | Yes |
| count         | Number of test packets     | 1-9999           | No (default: 100) |
| interval      | Time between packets       | 10-1000 ms       | No (default: 100) |
| padding       | Additional packet bytes    | 0-9000 bytes     | No (default: 0) |
| ttl           | Time to Live              | 1-255            | No (default: 64) |
| tos           | Type of Service           | 0-255            | No (default: 0) |
| do-not-fragment| Set DF bit               | flag             | No (IPv4 only) |

## Output Format

The test results display:
```
===============================================================================
Direction         Min         Max         Avg          Jitter     Loss     Pkts
-------------------------------------------------------------------------------
  Outbound:         160us       241us       188us        21us      0.0%     10/10
  Inbound:          259us       395us       290us        19us      0.0%     10/10
  Roundtrip:        427us       593us       478us        36us      0.0%    Total:10
-------------------------------------------------------------------------------
                                                 pathgate's Onyx Test [RFC5357]
===============================================================================
```

Where:
- **Direction**: Outbound (sender to responder), Inbound (responder to sender), Roundtrip
- **Min/Max/Avg**: Minimum, maximum and average delay in microseconds
- **Jitter**: Packet delay variation in microseconds
- **Loss**: Packet loss percentage
- **Pkts**: Packets transmitted/received (Tx/Rx)

## Error Handling

The plugin provides clear error messages for common issues:
- Invalid IP addresses
- Port numbers out of range
- Permission denied for privileged ports (<1024)
- Network connectivity issues
- Parameter validation errors

## Implementation Details

- Based on RFC 5357 TWAMP protocol specification
- Supports unauthenticated mode
- Uses UDP for test packets
- Implements both sender and responder roles
- Thread-safe implementation
- Graceful shutdown on interruption (Ctrl+C)

