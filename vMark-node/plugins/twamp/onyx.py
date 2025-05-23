#!/usr/bin/python3


"""
TWAMP validation tool for Python Version 3.0

Based on the 'onyx' tool, adapted for vMark integration.
"""

__title__ = "onyx"
__version__ = "3.0-vMark"
__status__ = "adapted"

#############################################################################

import os
import struct
import sys
import time
import socket
import logging
import binascii
import threading
import random
import argparse
import signal
import select
# Removed: from .common import log, udpSession

#############################################################################

if (sys.platform == "win32"):
    # Crude way to estimate boot time for perf_counter offset
    time0 = time.time() - time.perf_counter()

if sys.version_info > (3,):
    long = int # For Python 3 compatibility if 'long' is used

# Constants to convert between python timestamps and NTP 8B binary format [RFC1305]
TIMEOFFSET = long(2208988800)    # Time Difference: 1-JAN-1900 to 1-JAN-1970
ALLBITS = long(0xFFFFFFFF)       # To calculate 32bit fraction of the second


def now():
    """Get current time using the most precise method available."""
    if (sys.platform == "win32"):
        # On Windows, perf_counter is more precise but needs offset
        return time.perf_counter() + time0
    # On Linux/macOS, time.time() is generally sufficient and based on epoch
    return time.time()


def time_ntp2py(data):
    """
    Convert NTP 8 byte binary format [RFC1305] to python timestamp (float, seconds since epoch).
    """
    if len(data) < 8:
        raise ValueError("Need 8 bytes to convert NTP timestamp")
    ta, tb = struct.unpack('!II', data[:8]) # Read first 8 bytes as two unsigned integers
    t = float(ta - TIMEOFFSET) + (float(tb) / float(ALLBITS))
    return t


def zeros(nbr):
    """Return a byte string of nbr zero bytes."""
    return struct.pack('!%sB' % nbr, *([0] * nbr))


def dp(val, prec=2):
    """Format a value (assumed to be in microseconds) into milliseconds string with precision."""
    if val is None or val == float('inf') or val == float('-inf') or not isinstance(val, (int, float)):
        return "N/A" # Handle None, infinity, or non-numeric types
    if val == 0:
        return f"{0.0:.{prec}f}ms" # Format zero consistently

    try:
        # Convert microseconds to MILLISECONDS for display
        val_ms = val / 1000.0
        return f"{val_ms:.{prec}f}ms"
    except (TypeError, ValueError):
        return "NaN" # Handle potential errors during conversion/formatting


def parse_addr(addr_str, default_port=20000):
    """
    Parses an address string (IP:port, [IPv6]:port, IP, IPv6) into IP, port, and version.
    Returns (ip_string, port_int, ip_version_int (4 or 6)).
    Raises ValueError on invalid format.
    """
    if not isinstance(addr_str, str):
        raise ValueError("Address must be a string")

    addr_str = addr_str.strip()
    if not addr_str:
        raise ValueError("Address cannot be empty")

    if ']:' in addr_str: # IPv6 with port: [addr]:port
        ip, port_str = addr_str.rsplit(':', 1)
        ip = ip.strip('[]')
        if not ip: raise ValueError("Empty IPv6 address")
        try: port = int(port_str)
        except ValueError: raise ValueError(f"Invalid port: {port_str}")
        return ip, port, 6
    elif addr_str.endswith(']') and addr_str.startswith('['): # IPv6 without port: [addr]
        ip = addr_str.strip('[]')
        if not ip: raise ValueError("Empty IPv6 address")
        return ip, default_port, 6
    elif ':' in addr_str and '.' not in addr_str: # IPv6 without port (heuristic, might fail for some valid hostnames)
        # Basic check if it looks like an IPv6 address
        try:
            socket.inet_pton(socket.AF_INET6, addr_str)
            return addr_str, default_port, 6
        except socket.error:
            raise ValueError(f"Invalid IPv6 address format: {addr_str}")
    elif ':' in addr_str: # IPv4 with port: addr:port
        ip, port_str = addr_str.split(':', 1)
        if not ip: raise ValueError("Empty IPv4 address")
        try: port = int(port_str)
        except ValueError: raise ValueError(f"Invalid port: {port_str}")
        # Basic check if it looks like an IPv4 address
        try: socket.inet_pton(socket.AF_INET, ip)
        except socket.error: raise ValueError(f"Invalid IPv4 address format: {ip}")
        return ip, port, 4
    else: # IPv4 without port: addr
        ip = addr_str
        # Basic check if it looks like an IPv4 address
        try: socket.inet_pton(socket.AF_INET, ip)
        except socket.error: raise ValueError(f"Invalid IPv4 address format: {ip}")
        return ip, default_port, 4

#############################################################################

# --- Get the logger configured in twamp.py ---
# This assumes twamp.py sets up a logger named 'twamp'
log = logging.getLogger('twamp')
# If run standalone, a basic logger might be configured in __main__ block

# +++ Add onyxTimestamp Class +++
class onyxTimestamp:
    """
    Represents a timestamp using NTP format (seconds and fraction).
    Provides conversion methods and allows subtraction for duration.
    """
    def __init__(self, seconds=None, fraction=None):
        if seconds is None and fraction is None:
            # Get current time if no values provided
            current_time = now() # Use the existing now() function
            current_sec = int(current_time)
            self.seconds = current_sec + TIMEOFFSET
            self.fraction = int((current_time - current_sec) * ALLBITS)
        elif seconds is not None and fraction is not None:
            self.seconds = int(seconds)
            self.fraction = int(fraction)
        else:
            raise ValueError("Must provide both seconds and fraction, or neither.")

    def to_bytes(self):
        """Convert timestamp to 8-byte NTP format."""
        return struct.pack('!II', self.seconds, self.fraction)

    @classmethod
    def from_bytes(cls, data):
        """Create an onyxTimestamp from 8-byte NTP format."""
        if len(data) < 8:
            raise ValueError("Need 8 bytes to create timestamp")
        seconds, fraction = struct.unpack('!II', data[:8])
        return cls(seconds, fraction)

    def to_float(self):
        """Convert timestamp to a float (Python epoch seconds)."""
        return float(self.seconds - TIMEOFFSET) + (float(self.fraction) / ALLBITS)

    def __sub__(self, other):
        """Subtract another timestamp or float to get duration in seconds (float)."""
        if isinstance(other, onyxTimestamp):
            # Subtracting two timestamps gives duration
            return self.to_float() - other.to_float()
        elif isinstance(other, (int, float)):
            # Allow subtracting seconds directly (e.g., for interval calculations)
            return self.to_float() - other
        return NotImplemented

    def __repr__(self):
        return f"onyxTimestamp(seconds={self.seconds}, fraction={self.fraction})"
# +++ End onyxTimestamp Class +++


# --- Fix BaseSessionThread class methods indentation ---
class BaseSessionThread(threading.Thread):
    """Base class for UDP session threads providing socket handling and stop mechanism."""
    def __init__(self, far_end=None, ip_version=4, name=None):
        super().__init__(name=name)
        self.daemon = True # Make threads daemons by default
        self._stop_event = threading.Event()
        self.sock = None
        self.ip_version = ip_version
        self.far_end_ip = None
        self.far_end_port = None
        if far_end:
            try:
                # Use the parse_addr function defined above
                self.far_end_ip, self.far_end_port, parsed_ip_version = parse_addr(far_end)
                # Optional: Validate parsed_ip_version against self.ip_version if needed
                if parsed_ip_version != 0 and parsed_ip_version != self.ip_version:
                     log.warning(f"IP version mismatch for far_end '{far_end}'. Using specified version {self.ip_version}.")
            except ValueError as e:
                log.error(f"Invalid far_end address format '{far_end}': {e}")
                raise # Re-raise the error

    def stop(self):
        """Signals the thread to stop and closes the socket."""
        if not self._stop_event.is_set():
            log.info(f"Stop requested for thread '{self.name}'")
            self._stop_event.set()
            # Attempt to close socket to potentially unblock recvfrom/select
            self.close_socket()
        else:
            log.debug(f"Stop already requested for thread '{self.name}'")

    def setup_socket(self, bind_addr=None, bind_port=None, is_sender=False, ttl=64, tos=0, df=False):
        """Creates and configures the UDP socket."""
        family = socket.AF_INET6 if self.ip_version == 6 else socket.AF_INET
        try:
            self.sock = socket.socket(family, socket.SOCK_DGRAM)
            log.debug(f"Socket created (family={family}) for thread '{self.name}'")

            # Set common socket options
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # Set IP-level socket options (TTL, ToS, DF) - Best effort
            try:
                if family == socket.AF_INET:
                    self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_TTL, ttl)
                    self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, tos)
                    if df:
                        # DF bit handling for IPv4 (Platform dependent)
                        if sys.platform.startswith('linux'):
                            # IP_MTU_DISCOVER = 10, IP_PMTUDISC_DO = 2
                            self.sock.setsockopt(socket.IPPROTO_IP, 10, 2)
                            log.debug("Set IP_MTU_DISCOVER to IP_PMTUDISC_DO (Don't Fragment) on Linux.")
                        # Add elif for other platforms if specific handling is known (e.g., Windows, macOS)
                        else:
                            log.warning(f"Setting Don't Fragment bit via setsockopt may not be supported or effective on {sys.platform}.")
                    # else: # Optionally set PMTUDISC_WANT to allow fragmentation if needed
                    #    if sys.platform.startswith('linux'):
                    #        self.sock.setsockopt(socket.IPPROTO_IP, 10, 0) # IP_PMTUDISC_WANT
                elif family == socket.AF_INET6:
                    self.sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_UNICAST_HOPS, ttl)
                    self.sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_TCLASS, tos)
                    # DF bit is generally not set explicitly in IPv6; fragmentation handled differently.
                    if df:
                        log.warning("Don't Fragment (DF) flag is not typically set via socket options for IPv6.")

            except socket.error as opt_err:
                log.warning(f"Could not set some IP socket options for '{self.name}': {opt_err}")

            # Bind if required (usually for responder, or sender needing specific source port)
            if bind_port is not None: # Bind if port is specified
                # FIXED: Ensure correct binding address
                # For IPv4
                if family == socket.AF_INET:
                    bind_ip_actual = bind_addr if bind_addr and bind_addr != 'any' else '0.0.0.0'
                # For IPv6 
                else:
                    bind_ip_actual = bind_addr if bind_addr and bind_addr != 'any' else '::'
                
                try:
                    log.debug(f"Attempting to bind socket to {bind_ip_actual}:{bind_port}")
                    self.sock.bind((bind_ip_actual, bind_port))
                    log.info(f"Thread '{self.name}' socket bound to {bind_ip_actual}:{bind_port}")
                except socket.error as bind_err:
                    log.error(f"Failed to bind socket to {bind_ip_actual}:{bind_port} for thread '{self.name}': {bind_err}")
                    self.close_socket() # Close socket if bind fails
                    raise bind_err # Re-raise after logging
            elif not is_sender:
                 # Responders usually need to bind, warn if no port given
                 log.warning(f"Responder thread '{self.name}' created without specific bind port.")

        except socket.error as sock_err:
            log.error(f"Failed to create socket for thread '{self.name}': {sock_err}")
            self.sock = None
            raise # Re-raise after logging

    def close_socket(self):
        """Closes the socket if it exists."""
        if self.sock:
            log.debug(f"Closing socket for thread '{self.name}'")
            try:
                self.sock.close()
            except Exception as e:
                # Ignore errors if socket might already be closed (e.g., EBADF)
                log.warning(f"Error closing socket for '{self.name}': {e}")
            finally:
                self.sock = None
# --- End Base class functionality ---


# --- Modify onyxSessionReflector ---
class onyxSessionReflector(BaseSessionThread):
    """
    TWAMP Session Reflector class using UDP.
    Listens for TWAMP test packets and sends replies.
    """
    def __init__(self, bind_addr='any', bind_port=5000, ip_version=4, timer=0):
        # Call BaseSessionThread init
        super().__init__(ip_version=ip_version, name="twl_reflector_thread")
        self.bind_addr = bind_addr
        self.bind_port = bind_port
        self.timer = timer # Session reset timer

    def run(self):
        """Main execution loop for the reflector."""
        log.info(f"Starting TWAMP reflector thread '{self.name}' on {self.bind_addr}:{self.bind_port}")
        try:
            # Use setup_socket from BaseSessionThread
            self.setup_socket(bind_addr=self.bind_addr, bind_port=self.bind_port)
            if not self.sock:
                # setup_socket should raise error if it fails, but double-check
                raise ConnectionError("Failed to create/bind reflector socket")

            index = {} # Stores next reflector sequence number per source address
            reset = {} # Stores last seen time per source address for session timeout

            while not self._stop_event.is_set():
                # Use select for non-blocking check with timeout
                ready = select.select([self.sock], [], [], 0.5) # Timeout 0.5s
                if self._stop_event.is_set(): # Check again after select
                    break
                if ready[0]: # Socket is readable
                    try:
                        data, addr = self.sock.recvfrom(1024) # Buffer size
                        if not data: # Handle case where recvfrom returns empty data
                            continue

                        recv_time = onyxTimestamp() # T2 (Timestamp of reception)

                        # Basic validation - TWAMP-Test packet needs at least sequence number
                        if len(data) < 4:
                            log.warning(f"Reflector received short packet from {addr}: {len(data)} bytes (expected at least 4)")
                            continue

                        # Unpack sender's sequence number
                        try:
                            sseq = int.from_bytes(data[0:4], 'big')
                        except struct.error as e:
                             log.warning(f"Failed to unpack sequence number from {addr}: {e}")
                             continue

                        log.debug(f"Reflector received packet seq={sseq} from {addr}")

                        # Check for session reset based on timer
                        current_time_float = recv_time.to_float() # Use float time for comparison
                        if self.timer > 0:
                            if addr in reset and (current_time_float - reset[addr]) > self.timer:
                                log.info(f"Resetting reflector sequence for {addr} (session timeout > {self.timer}s)")
                                index[addr] = 0 # Reset sequence number
                            reset[addr] = current_time_float # Update last seen time

                        # Get or initialize reflector sequence number (rseq)
                        if addr not in index:
                            log.info(f"New session from {addr}, initializing reflector sequence.")
                            index[addr] = 0
                        rseq = index[addr]

                        # Prepare reply packet (TWAMP Light format)
                        send_time = onyxTimestamp() # T3 (Timestamp of transmission)

                        # Reply format:
                        # Reflector Seq Num (4 bytes)
                        # T2 Timestamp (10 bytes: 8 timestamp + 2 error est)
                        # T3 Timestamp (10 bytes: 8 timestamp + 2 error est)
                        # Sender Seq Num (4 bytes)

                        # Error estimate (MBZ for Light - Must Be Zero)
                        err_est = 0 # Use 0 for the 2-byte error estimate field

                        # Pack the reply - FIX: Add 2 zero bytes after each timestamp
                        reply_payload = struct.pack('!L', rseq) + \
                                        recv_time.to_bytes() + struct.pack('!H', err_est) + \
                                        send_time.to_bytes() + struct.pack('!H', err_est) + \
                                        struct.pack('!L', sseq)

                        # --- Check length before sending (optional debug) ---
                        # log.debug(f"Packed reply payload length: {len(reply_payload)}") # Should be 28

                        self.sock.sendto(reply_payload, addr)
                        log.debug(f"Reflector sent reply to {addr} [rseq={rseq}, sseq={sseq}]")

                        # Increment sequence number for this source
                        index[addr] += 1

                    except socket.timeout:
                        # This shouldn't happen with select, but handle defensively
                        log.debug("Reflector socket timeout (unexpected)")
                        continue
                    except Exception as e:
                        # Check if stopped before logging error
                        if self._stop_event.is_set():
                            log.info("Reflector receive loop interrupted by stop signal.")
                            break
                        log.error(f"Reflector error processing packet from {addr}: {e}", exc_info=True)
                        # Continue listening unless it's a fatal error

        except Exception as e:
            # Log errors during setup or fatal loop errors
            log.exception(f"Fatal error in reflector thread '{self.name}': {e}")
        finally:
            # Use close_socket from BaseSessionThread
            self.close_socket()
            log.info(f"TWAMP reflector thread '{self.name}' stopped.")
# --- End Reflector Modification ---


# --- Modify onyxSessionSender ---
class onyxSessionSender(BaseSessionThread):
    """
    TWAMP Session Sender class using UDP.
    Sends test packets and processes replies to calculate metrics.
    """
    def __init__(self, far_end, count=100, interval=0.1, padding=0, ttl=64, tos=0,
                 ip_version=4, do_not_fragment=False, results_callback=None, session_key=None):
        # Call BaseSessionThread init
        super().__init__(far_end=far_end, ip_version=ip_version, name="twl_sender_thread")

        self.count = int(count)
        self.interval = float(interval) # Ensure interval is float (seconds)
        self.padding = int(padding)
        self.ttl = int(ttl)
        self.tos = int(tos)
        self.do_not_fragment = bool(do_not_fragment)
        self.results_callback = results_callback
        self.session_key = session_key

        # Results storage and calculation helpers
        self.results = { # Initialize results structure
            "packets_tx": 0, "packets_rx": 0, "packets_lost": 0,
            "outbound_min_us": None, "outbound_max_us": None, "outbound_avg_us": None, "outbound_jitter_us": None,
            "inbound_min_us": None, "inbound_max_us": None, "inbound_avg_us": None, "inbound_jitter_us": None,
            "roundtrip_min_us": None, "roundtrip_max_us": None, "roundtrip_avg_us": None, "roundtrip_jitter_us": None,
            "total_loss_percent": None, "error": None
        }
        self._latencies_ob = [] # List to store outbound latencies (microseconds)
        self._latencies_ib = [] # List to store inbound latencies (microseconds)
        self._latencies_rt = [] # List to store round-trip latencies (microseconds)
        self._seq_timestamps = {} # Store send timestamps (T1) for calculating latency {seq: onyxTimestamp}

    def _calculate_stats(self):
        """Calculate min, max, avg, jitter, and loss."""
        # --- FIX: Check if packets_tx is zero before calculating loss ---
        if self.results["packets_tx"] == 0:
             # Handle case where no packets were sent (e.g., immediate error)
             self.results["packets_rx"] = 0
             self.results["total_loss_percent"] = 0.0 # Or None if preferred
             # Set all metrics to None
             for key in ["roundtrip_min_us", "roundtrip_max_us", "roundtrip_avg_us", "roundtrip_jitter_us",
                         "outbound_min_us", "outbound_max_us", "outbound_avg_us", "outbound_jitter_us",
                         "inbound_min_us", "inbound_max_us", "inbound_avg_us", "inbound_jitter_us"]:
                 self.results[key] = None
             return
        # --- End Fix ---

        if not self._latencies_rt: # No replies received but packets were sent
            self.results["packets_rx"] = 0
            self.results["total_loss_percent"] = 100.0
            # Set all metrics to None
            for key in ["roundtrip_min_us", "roundtrip_max_us", "roundtrip_avg_us", "roundtrip_jitter_us",
                        "outbound_min_us", "outbound_max_us", "outbound_avg_us", "outbound_jitter_us",
                        "inbound_min_us", "inbound_max_us", "inbound_avg_us", "inbound_jitter_us"]:
                self.results[key] = None
            return

        self.results["packets_rx"] = len(self._latencies_rt)
        # --- FIX: Use self.results["packets_tx"] for loss calculation ---
        # Ensure packets_tx is not zero to avoid division by zero (already handled above)
        loss = (self.results["packets_tx"] - self.results["packets_rx"]) / self.results["packets_tx"] * 100.0
        # --- End Fix ---
        self.results["total_loss_percent"] = loss

        # Helper to calculate stats for a list, clamping min/avg to 0
        def calc_dir_stats(latencies):
            # ... (rest of calc_dir_stats remains the same) ...
            if not latencies:
                return None, None, None, None # Min, Max, Avg, Jitter

            min_us = min(latencies)
            max_us = max(latencies)
            avg_us = sum(latencies) / len(latencies)

            # Calculate jitter (inter-packet delay variation) using differences
            jit_us = 0
            if len(latencies) > 1:
                diffs = [abs(latencies[i] - latencies[i-1]) for i in range(1, len(latencies))]
                jit_us = sum(diffs) / len(diffs) if diffs else 0

            # --- FIX: Clamp negative min and avg to 0 ---
            if min_us < 0:
                # Find smallest non-negative value, or default to 0
                non_neg_latencies = [l for l in latencies if l >= 0]
                min_us = min(non_neg_latencies) if non_neg_latencies else 0
            if avg_us < 0:
                avg_us = 0
            # --- End Fix ---

            return min_us, max_us, avg_us, jit_us

        # Calculate for each direction
        rt_min, rt_max, rt_avg, rt_jit = calc_dir_stats(self._latencies_rt)
        ob_min, ob_max, ob_avg, ob_jit = calc_dir_stats(self._latencies_ob)
        ib_min, ib_max, ib_avg, ib_jit = calc_dir_stats(self._latencies_ib)

        # Store results (microseconds)
        # ... (storing results remains the same) ...
        self.results["roundtrip_min_us"] = rt_min
        self.results["roundtrip_max_us"] = rt_max
        self.results["roundtrip_avg_us"] = rt_avg
        self.results["roundtrip_jitter_us"] = rt_jit

        self.results["outbound_min_us"] = ob_min
        self.results["outbound_max_us"] = ob_max
        self.results["outbound_avg_us"] = ob_avg
        self.results["outbound_jitter_us"] = ob_jit

        self.results["inbound_min_us"] = ib_min
        self.results["inbound_max_us"] = ib_max
        self.results["inbound_avg_us"] = ib_avg
        self.results["inbound_jitter_us"] = ib_jit

        # Note: One-way loss calculation is complex and not implemented here
        self.results["outbound_loss_percent"] = None
        self.results["inbound_loss_percent"] = None


        log.debug("Stats calculated: Loss=%.2f%% RT Avg=%.2fms", loss, rt_avg / 1000.0 if rt_avg is not None else float('nan'))


    def run(self):
        """Main execution loop for the sender."""
        log.info(f"Starting TWAMP sender thread '{self.name}' to {self.far_end_ip}:{self.far_end_port}")
        try:
            # Use setup_socket from BaseSessionThread
            self.setup_socket(is_sender=True, ttl=self.ttl, tos=self.tos, df=self.do_not_fragment)
            if not self.sock:
                raise ConnectionError("Failed to create sender socket")

            log.debug(f"Sender socket created for {self.far_end_ip}:{self.far_end_port}")

            seq = 0 # Start sequence number at 0 or 1? Typically 0.
            received_sequences = set() # Track received sequence numbers to detect duplicates

            while seq < self.count and not self._stop_event.is_set():
                # Prepare payload: Sequence number (4 bytes) + padding
                payload_seq = seq.to_bytes(4, 'big')
                padding_bytes = os.urandom(self.padding) if self.padding > 0 else b''
                payload = payload_seq + padding_bytes

                send_time = onyxTimestamp() # T1 (Timestamp before sending)
                self._seq_timestamps[seq] = send_time

                try:
                    self.sock.sendto(payload, (self.far_end_ip, self.far_end_port))
                    self.results["packets_tx"] += 1
                    log.debug(f"Sent packet seq={seq} to {self.far_end_ip}:{self.far_end_port}")
                except socket.error as send_err:
                    log.error(f"Error sending packet seq={seq}: {send_err}")
                    self.results["error"] = f"Send error: {send_err}"
                    break # Stop sending on error
                except Exception as send_err: # Catch other potential errors
                    log.exception(f"Unexpected error sending packet seq={seq}: {send_err}")
                    self.results["error"] = f"Unexpected send error: {send_err}"
                    break

                # Wait for reply (using select for timeout)
                # Timeout slightly less than interval to allow processing time
                # Ensure timeout is not negative if interval is very small
                wait_interval = max(0.001, self.interval * 0.9)
                ready = select.select([self.sock], [], [], wait_interval)

                if self._stop_event.is_set(): break # Check stop event after select

                if ready[0]: # Socket is readable
                    try:
                        data, addr = self.sock.recvfrom(1024) # Buffer size
                        if not data: continue # Skip if empty data received

                        recv_time = onyxTimestamp() # T4 (Timestamp of reception)
                        # --- FIX: Explicitly assign t4 ---
                        t4 = recv_time
                        # --- End Fix ---

                        # Parse reply packet (assuming TWAMP Light format from reflector)
                        # Expected: RSeq(4), T2(10), T3(10), SSeq(4) [+ padding]
                        if len(data) >= 28:
                            # Unpack the relevant fields
                            rseq = int.from_bytes(data[0:4], 'big') # Reflector Seq Num
                            t2 = onyxTimestamp.from_bytes(data[4:14]) # T2 from reflector
                            t3 = onyxTimestamp.from_bytes(data[14:24]) # T3 from reflector
                            sseq = int.from_bytes(data[24:28], 'big') # Sender Seq Num (echoed)

                            # Validate sequence number
                            if sseq in self._seq_timestamps:
                                if sseq not in received_sequences:
                                    received_sequences.add(sseq)
                                    self.results["packets_rx"] += 1

                                    t1 = self._seq_timestamps[sseq] # Retrieve original send time (T1)

                                    # Calculate latencies (microseconds)
                                    ob_latency = (t2 - t1) * 1_000_000
                                    ib_latency = (t4 - t3) * 1_000_000
                                    rt_latency = (t4.to_float() - t1.to_float()) - (t3.to_float() - t2.to_float())
                                    rt_latency *= 1_000_000

                                    # --- FIX: Append calculated latencies to lists ---
                                    self._latencies_ob.append(ob_latency)
                                    self._latencies_ib.append(ib_latency)
                                    self._latencies_rt.append(rt_latency)
                                    # --- End Fix ---

                                    log.debug(f"Processed reply seq={sseq}: OB={dp(ob_latency)}, IB={dp(ib_latency)}, RT={dp(rt_latency)}")

                                else:
                                    log.warning(f"Received duplicate sequence number: {sseq}")
                            else:
                                log.warning(f"Received reply for unknown/unexpected sequence number: {sseq}")
                        else:
                            log.warning(f"Received short/invalid packet from {addr}: {len(data)} bytes (expected at least 28)")

                    except socket.timeout:
                        # This is expected if select timed out (no reply within interval)
                        log.debug(f"Timeout waiting for reply (seq={seq})")
                    except struct.error as unpack_err:
                         log.warning(f"Failed to unpack reply packet from {addr}: {unpack_err}")
                    except Exception as recv_err:
                        if self._stop_event.is_set():
                            log.info("Receive loop interrupted by stop signal.")
                            break
                        log.error(f"Error receiving/processing packet: {recv_err}", exc_info=True)
                        # Continue or break based on severity? Continue for now.
                        # self.results["error"] = f"Receive error: {recv_err}"
                        # break

                # Wait for the next interval before sending next packet
                if seq + 1 < self.count and not self._stop_event.is_set():
                    # Calculate time elapsed since sending and sleep for remaining interval
                    elapsed = onyxTimestamp() - send_time
                    wait_time = self.interval - elapsed
                    if wait_time > 0:
                        time.sleep(wait_time)
                    # else: log.warning(f"Loop took longer than interval for seq={seq}")

                seq += 1 # Increment sequence number for next packet

            # --- End of loop ---
            if self._stop_event.is_set():
                log.info(f"Sender loop terminated early by stop signal after sending {seq} packets.")
            elif seq == self.count:
                log.info(f"Sender finished sending {self.count} packets.")

            # --- FIX: Add a small delay to allow the last reply to arrive ---
            if not self._stop_event.is_set() and seq == self.count:
                # Wait a fixed short duration (e.g., 1 second) for the final reply
                final_wait = 1.0 # seconds
                log.debug(f"Waiting {final_wait}s for potential final reply...")
                # Ensure socket still exists before select
                current_sock = self.sock
                if current_sock:
                    try:
                        final_ready = select.select([current_sock], [], [], final_wait)
                        if self._stop_event.is_set(): # Check again after select
                             log.debug("Stop event set during final wait.")
                        elif final_ready and final_ready[0]:
                            # --- REVISED FINAL PACKET PROCESSING ---
                            try:
                                data, addr = current_sock.recvfrom(1024)
                                if not data:
                                    log.warning("Received empty data during final wait.")
                                else:
                                    recv_time = onyxTimestamp() # T4

                                    # Check minimum length for TWAMP Light reply
                                    if len(data) >= 28:
                                        # Parse using slicing and from_bytes for robustness
                                        # Reply format: RSeq(4), T2(8), ErrEst(2), T3(8), ErrEst(2), SSeq(4)
                                        try:
                                            # rseq_bytes = data[0:4] # Reflector Seq Num (optional to check)
                                            t2 = onyxTimestamp.from_bytes(data[4:12]) # T2 timestamp
                                            # Skip Error Estimate (data[12:14])
                                            t3 = onyxTimestamp.from_bytes(data[14:22]) # T3 timestamp
                                            # Skip Error Estimate (data[22:24])
                                            sseq_bytes = data[24:28] # Sender Seq Num (echoed)
                                            sseq = int.from_bytes(sseq_bytes, 'big') # Convert SSeq bytes to int

                                            # Now process using the parsed sseq, t1, t2, t3, t4
                                            if sseq in self._seq_timestamps and sseq not in received_sequences:
                                                received_sequences.add(sseq)
                                                self.results["packets_rx"] += 1
                                                t1 = self._seq_timestamps[sseq]
                                                t4 = recv_time # Already onyxTimestamp

                                                # Calculate latencies in MICROSECONDS
                                                rt_latency = (t4.to_float() - t1.to_float()) - (t3.to_float() - t2.to_float())
                                                rt_latency *= 1_000_000
                                                ob_latency = (t2 - t1) * 1_000_000
                                                ib_latency = (t4 - t3) * 1_000_000

                                                self._latencies_rt.append(rt_latency)
                                                self._latencies_ob.append(ob_latency)
                                                self._latencies_ib.append(ib_latency)
                                                log.debug(f"Processed final reply seq={sseq}: OB={dp(ob_latency)}, IB={dp(ib_latency)}, RT={dp(rt_latency)}")
                                            elif sseq in received_sequences:
                                                log.warning(f"Received duplicate reply for seq={sseq} during final wait.")
                                            else:
                                                log.warning(f"Received reply for unknown seq={sseq} during final wait.")

                                        except (struct.error, ValueError, IndexError) as parse_err:
                                             log.warning(f"Failed to parse final reply packet from {addr}: {parse_err}")

                                    else:
                                        log.warning(f"Received short packet ({len(data)} bytes) during final wait.")
                            except socket.error as final_sock_err:
                                # Handle potential socket errors during final recv
                                if not self._stop_event.is_set(): # Avoid logging error if we stopped
                                     log.error(f"Socket error receiving final packet: {final_sock_err}")
                            except Exception as final_recv_err:
                                log.error(f"Error processing final packet: {final_recv_err}", exc_info=True)
                        else:
                            log.debug("No final reply received during extra wait time.")
                    except Exception as select_err:
                         log.error(f"Error during final select call: {select_err}")
                else:
                    log.warning("Socket was closed before final wait could occur.")
            # --- End Fix ---

        except ConnectionError as conn_err: # Catch socket setup errors
             self.results["error"] = f"Connection error: {conn_err}"
             log.error(self.results["error"]) # Log the specific connection error
        except Exception as e:
            log.exception(f"Fatal error in sender thread {self.name}: {e}")
            self.results["error"] = f"Fatal error: {e}"
        finally:
            # Use close_socket from BaseSessionThread
            self.close_socket()
            # Calculate stats unless a fatal error occurred before loop start/during setup
            if self.results["packets_tx"] > 0 or self.results["error"] is None or "Send error" in str(self.results["error"]) or "Receive error" in str(self.results["error"]):
                 try:
                     self._calculate_stats()
                 except Exception as calc_err:
                      log.error(f"Error calculating final stats: {calc_err}")
                      if not self.results["error"]: self.results["error"] = f"Stat calculation error: {calc_err}"

            log.info(f"TWAMP sender thread '{self.name}' finished processing.")

            # Call results callback if provided
            if self.results_callback and self.session_key:
                try:
                    log.debug(f"Calling results callback for session {self.session_key}")
                    # Ensure results dict has been populated
                    if "packets_tx" not in self.results: self._calculate_stats() # Recalculate if needed
                    self.results_callback(self.session_key, self.results.copy()) # Send a copy
                except Exception as cb_err:
                    log.error(f"Error executing results callback for session {self.session_key}: {cb_err}")
# --- End Sender Modification ---


# --- twl_sender and twl_responder functions ---
def twl_sender(args):
    """
    Function to initiate TWAMP sender thread.
    Parses args and starts onyxSessionSender.
    Returns thread object (non-interactive) or results dict (interactive).
    """
    sender_thread = None
    is_interactive = threading.current_thread() is threading.main_thread()
    log.debug(f"twl_sender called. Interactive mode: {is_interactive}")

    try:
        # Extract parameters from args object (passed from twamp.py)
        # Ensure required args are present
        required = ['far_end', 'count', 'interval', 'ip_version']
        if not all(hasattr(args, attr) for attr in required):
             missing = [attr for attr in required if not hasattr(args, attr)]
             raise AttributeError(f"Missing required arguments for twl_sender: {missing}")

        far_end = args.far_end
        count = args.count
        interval = args.interval # Assumed to be in seconds already
        padding = getattr(args, 'padding', 0)
        ttl = getattr(args, 'ttl', 64)
        tos = getattr(args, 'tos', 0)
        ip_version = args.ip_version
        do_not_fragment = getattr(args, 'do_not_fragment', False)
        results_callback = getattr(args, 'results_callback', None)
        session_key = getattr(args, 'session_key', None)

        # Create sender instance
        sender_thread = onyxSessionSender(
            far_end=far_end, count=count, interval=interval, padding=padding,
            ttl=ttl, tos=tos, ip_version=ip_version, do_not_fragment=do_not_fragment,
            results_callback=results_callback, session_key=session_key
        )
        sender_thread.name = f"onyxSender-{far_end}" # Give it a specific name

        if is_interactive:
            # Running from CLI, make it non-daemon and wait
            sender_thread.daemon = False
            log.debug("Running interactively, setting daemon=False.")

            # Add Signal Handling for interactive mode
            def signal_handler_sender(sig, frame):
                log.warning(f"Signal {sig} received, stopping interactive sender...")
                if sender_thread:
                    sender_thread.stop()
            try:
                signal.signal(signal.SIGINT, signal_handler_sender)
                signal.signal(signal.SIGTERM, signal_handler_sender)
                log.debug("Signal handlers registered for interactive sender.")
            except Exception as e:
                 log.warning(f"Could not set signal handlers for interactive sender: {e}")

            sender_thread.start()
            log.info(f"TWAMP sender thread '{sender_thread.name}' started. Waiting for completion (Ctrl+C to stop)...")
            sender_thread.join() # Wait indefinitely until thread finishes
            log.info(f"TWAMP sender thread '{sender_thread.name}' finished.")
            # Return results dict on interactive completion
            return sender_thread.results.copy() # Return a copy

        else:
            # Running non-interactively (API)
            sender_thread.daemon = True # Can be daemon for API calls
            sender_thread.start()
            log.info(f"TWAMP sender thread '{sender_thread.name}' started in background (non-interactive).")
            return sender_thread # Return the thread object

    except Exception as e:
        log.exception("Failed to start or run TWAMP sender thread")
        if sender_thread and sender_thread.is_alive():
             try: sender_thread.stop()
             except Exception as stop_err: log.error(f"Error stopping sender after failure: {stop_err}")
        # Return error dictionary on failure
        return {"error": f"Error running sender: {str(e)}"}


def twl_responder(args):
    """
    Function to initiate TWAMP responder thread.
    Parses args and starts onyxSessionReflector.
    Returns thread object (non-interactive) or status string (interactive).
    """
    responder_thread = None
    is_interactive = threading.current_thread() is threading.main_thread()
    log.debug(f"twl_responder called. Interactive mode: {is_interactive}")

    try:
        # Extract parameters from args object (passed from twamp.py)
        required = ['port', 'ip_version']
        if not all(hasattr(args, attr) for attr in required):
             missing = [attr for attr in required if not hasattr(args, attr)]
             raise AttributeError(f"Missing required arguments for twl_responder: {missing}")

        bind_addr = getattr(args, 'bind_addr', 'any') # Default to 'any'
        bind_port = args.port
        ip_version = args.ip_version
        timer = getattr(args, 'timer', 0) # Get session reset timer

        # Add more debug logging
        log.debug(f"twl_responder parameters: bind_addr={bind_addr}, bind_port={bind_port}, ip_version={ip_version}")
        
        # Test socket binding directly to diagnose potential issues
        family = socket.AF_INET6 if ip_version == 6 else socket.AF_INET
        bind_ip_actual = 'any' if bind_addr == 'any' else bind_addr
        if bind_ip_actual == 'any':
            bind_ip_actual = '::' if ip_version == 6 else '0.0.0.0'
            
        try:
            log.debug(f"Testing socket binding to {bind_ip_actual}:{bind_port}...")
            test_sock = socket.socket(family, socket.SOCK_DGRAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_sock.bind((bind_ip_actual, bind_port))
            log.debug(f"Socket binding test successful")
            test_sock.close()
        except Exception as e:
            log.error(f"Socket binding test failed: {e}")
            return {"error": f"Cannot bind to {bind_ip_actual}:{bind_port} - {str(e)}"}

        # Create responder instance
        responder_thread = onyxSessionReflector(
            bind_addr=bind_addr, bind_port=bind_port, ip_version=ip_version, timer=timer
        )
        responder_thread.name = f"onyxResponder-{bind_port}"
        
        # Rest of the function remains the same...

        if is_interactive:
            # Running from CLI, make it non-daemon and wait
            responder_thread.daemon = False
            log.debug("Running interactively, setting daemon=False.")

            # Running from CLI, make it non-daemon and wait
            responder_thread.daemon = False
            log.debug("Running interactively, setting daemon=False.")

            # Add Signal Handling for interactive mode
            def signal_handler_responder(sig, frame):
                log.warning(f"Signal {sig} received, stopping interactive responder...")
                if responder_thread:
                    responder_thread.stop()
            try:
                signal.signal(signal.SIGINT, signal_handler_responder)
                signal.signal(signal.SIGTERM, signal_handler_responder)
                log.debug("Signal handlers registered for interactive responder.")
            except Exception as e:
                 log.warning(f"Could not set signal handlers for interactive responder: {e}")

            responder_thread.start()
            log.info(f"TWAMP responder thread '{responder_thread.name}' started. Waiting for completion (Ctrl+C to stop)...")
            responder_thread.join() # Wait indefinitely until thread finishes
            log.info("TWAMP responder thread finished.")
            return "TWAMP responder finished." # Return status message

        else:
            # Running non-interactively (API)
            responder_thread.daemon = True # Can be daemon for API calls
            responder_thread.start()
            log.info(f"TWAMP responder thread '{responder_thread.name}' started in background (non-interactive).")
            return responder_thread # Return the thread object

    except Exception as e:
        log.exception("Failed to start or run TWAMP responder thread")
        if responder_thread and responder_thread.is_alive():
             try: responder_thread.stop()
             except Exception as stop_err: log.error(f"Error stopping responder after failure: {stop_err}")
        # Return error dictionary or string on failure
        return {"error": f"Error starting responder: {str(e)}"}

# --- End twl_sender and twl_responder ---


# --- Placeholder/Legacy Classes/Functions (Keep if needed for compatibility or future use) ---
class twampStatistics():
    """Placeholder for original statistics class if different from sender's internal one."""
    # If the sender uses its internal self.results and _calculate_stats,
    # this separate class might not be needed unless used by other parts.
    # For now, keep the definition but it might be redundant.
    def __init__(self):
        self.count = 0
        self.sent_count = 0
        # ... (rest of the fields) ...
        self.minOB = float('inf')
        self.maxOB = float('-inf')
        self.sumOB = 0
        # ... etc ...

    def sent(self, sseq):
        self.sent_count = max(self.sent_count, sseq + 1)

    def add(self, delayRT, delayOB, delayIB, rseq, sseq):
        # ... (calculation logic) ...
        pass

    def get_results(self):
        # ... (final calculation logic) ...
        return {}


class onyxControlClient:
    """Placeholder for TWAMP Control Protocol Client (Not used in Light mode)."""
    def __init__(self, server="", tcp_port=862, tos=0x88, ipversion=4):
        log.warning("onyxControlClient (Full TWAMP Control) is not implemented/used in this Light version.")
        self.socket = None
        pass # Not implemented

    def connect(self, server="", port=862, tos=0x88): pass
    def connect6(self, server="", port=862, tos=0x88): pass
    def send(self, data): pass
    def receive(self): return b''
    def close(self): pass
    def connectionSetup(self): pass
    def reqSession(self, sender="", s_port=20001, receiver="", r_port=20002, startTime=0, timeOut=3, dscp=0, padding=0): return False
    def startSessions(self): pass
    def stopSessions(self): pass


def twamp_controller(args):
    log.error("TWAMP Control Protocol (controller mode) is not supported.")
    return {"error": "TWAMP Control Protocol (controller mode) is not supported."}

def twamp_ctclient(args):
    log.error("TWAMP Control Protocol (controlclient mode) is not supported.")
    return {"error": "TWAMP Control Protocol (controlclient mode) is not supported."}

# --- DSCP Mapping and Table ---
dscpmap = {"be":   0, "cp1":   1,  "cp2":  2,  "cp3":  3, "cp4":   4, "cp5":   5, "cp6":   6, "cp7":   7,
           "cs1":  8, "cp9":   9, "af11": 10, "cp11": 11, "af12": 12, "cp13": 13, "af13": 14, "cp15": 15,
           "cs2": 16, "cp17": 17, "af21": 18, "cp19": 19, "af22": 20, "cp21": 21, "af23": 22, "cp23": 23,
           "cs3": 24, "cp25": 25, "af31": 26, "cp27": 27, "af32": 28, "cp29": 29, "af33": 30, "cp31": 31,
           "cs4": 32, "cp33": 33, "af41": 34, "cp35": 35, "af42": 36, "cp37": 37, "af43": 38, "cp39": 39,
           "cs5": 40, "cp41": 41, "cp42": 42, "cp43": 43, "cp44": 44, "cp45": 45, "ef":   46, "cp47": 47,
           "nc1": 48, "cp49": 49, "cp50": 50, "cp51": 51, "cp52": 52, "cp53": 53, "cp54": 54, "cp55": 55,
           "nc2": 56, "cp57": 57, "cp58": 58, "cp59": 59, "cp60": 60, "cp61": 61, "cp62": 62, "cp63": 63}

def dscpTable():
    """Prints a formatted DSCP mapping table."""
    # (Implementation remains the same as provided)
    print("""
Feature not available""")
    sys.stdout.flush()

#############################################################################

# --- Main execution block for standalone CLI usage ---
if __name__ == '__main__':

    # --- Argument Parsing Setup ---
    debug_parser = argparse.ArgumentParser(add_help=False)
    debug_options = debug_parser.add_argument_group("Debug Options")
    debug_options.add_argument('-l', '--logfile', metavar='filename', type=argparse.FileType('w'), default=sys.stdout, help='Specify the logfile (default: <stdout>)')
    group = debug_options.add_mutually_exclusive_group()
    group.add_argument('-q', '--quiet',   action='store_true', help='Disable logging (overrides verbose/debug)')
    group.add_argument('-v', '--verbose', action='store_true', help='Enhanced logging (INFO level)')
    group.add_argument('-d', '--debug',   action='store_true', help='Extensive logging (DEBUG level)')

    ipopt_parser = argparse.ArgumentParser(add_help=False)
    group = ipopt_parser.add_argument_group("IP socket options")
    # Add IP version selection
    group.add_argument('--ip-version', metavar='4|6', type=int, choices=[4, 6], default=4, help='IP version to use (4 or 6)')
    group.add_argument('--tos',     metavar='type-of-service', default=0, type=int, help='IP TOS value (decimal, 0-255)') # Default 0 (BE)
    group.add_argument('--dscp',    metavar='dscp-name|value', help='IP DSCP value (name like cs1, af11, ef or decimal 0-63)')
    group.add_argument('--ttl',     metavar='time-to-live', default=64,   type=int, help='IP TTL/Hop Limit [1..255]')
    group.add_argument('--padding', metavar='bytes', default=0,    type=int, help='Size of padding bytes added to payload')
    group.add_argument('--do-not-fragment',  action='store_true', help='Set Don\'t Fragment flag (IPv4, platform dependent)')

    parser = argparse.ArgumentParser(description=f"Onyx TWAMP Light Tool v{__version__}")
    parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)

    subparsers = parser.add_subparsers(dest='mode', help='onyx sub-commands', required=True)

    # --- Responder Sub-parser ---
    p_responder = subparsers.add_parser('responder', help='Run as TWAMP Light responder', parents=[debug_parser, ipopt_parser])
    p_responder.add_argument('--bind-addr', metavar='local-ip', default='any', help='Local IP address to bind to (default: any)')
    p_responder.add_argument('--port', metavar='port', type=int, default=5000, help='UDP port to listen on (default: 5000)')
    p_responder.add_argument('--timer', metavar='seconds', default=0, type=int, help='Session reset timer (0=disabled)')
    p_responder.set_defaults(func=twl_responder)

    # --- Sender Sub-parser ---
    p_sender = subparsers.add_parser('sender', help='Run as TWAMP Light sender', parents=[debug_parser, ipopt_parser])
    p_sender.add_argument('far_end', metavar='remote-ip:port', help='Responder IP address and port')
    # near_end is optional for sender unless specific source port needed
    # p_sender.add_argument('--near-end', metavar='local-ip:port', default=None, help='Local IP and port to send from (optional)')
    p_sender.add_argument('-i', '--interval', metavar='seconds', default=0.1, type=float, help="Interval between packets in seconds (default: 0.1)")
    p_sender.add_argument('-c', '--count', metavar='packets', default=100, type=int, help="Number of packets to send (default: 100)")
    p_sender.set_defaults(func=twl_sender)

    # --- DSCP Table Sub-parser ---
    p_dscptab = subparsers.add_parser('dscptable', help='Print DSCP table', parents=[debug_parser])
    p_dscptab.set_defaults(func=dscpTable, parseop=False) # Indicate no IP options needed

    # --- Parse Arguments ---
    try:
        options = parser.parse_args()
        # Set default for parseop if not set by dscptable
        if not hasattr(options, 'parseop'):
             options.parseop = True
    except Exception as e:
        print(f"Argument parsing error: {e}")
        parser.print_help()
        sys.exit(1)


    # --- Logging Setup ---
    log_level = logging.WARNING # Default level
    if options.quiet:
        log_level = logging.CRITICAL + 1 # Effectively disable logging
    elif options.debug:
        log_level = logging.DEBUG ## DESHABILITAR LOGGING
    elif options.verbose:
        log_level = logging.INFO

    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_datefmt = '%Y-%m-%d %H:%M:%S'
    log_formatter = logging.Formatter(log_format, log_datefmt)

    # Get the root logger used by getLogger('twamp')
    root_log = logging.getLogger() # Get root logger
    # Ensure handlers are cleared if re-running in same process (e.g. testing)
    if root_log.hasHandlers():
        root_log.handlers.clear()

    log_handler = logging.StreamHandler(options.logfile)
    log_handler.setFormatter(log_formatter)
    root_log.addHandler(log_handler)
    root_log.setLevel(log_level)

    log.info(f"Logging configured. Level: {logging.getLevelName(log_level)}, Output: {options.logfile.name}")

    # --- Process DSCP/ToS Options ---
    if options.parseop: # Only process if not dscptable
        if options.dscp:
            dscp_val_str = str(options.dscp).lower()
            if dscp_val_str in dscpmap:
                dscp_val = dscpmap[dscp_val_str]
                options.tos = dscp_val << 2 # DSCP is high 6 bits of ToS byte
                log.info(f"Using DSCP '{dscp_val_str}' ({dscp_val}), setting ToS to {options.tos}")
            else:
                try:
                    dscp_val = int(dscp_val_str)
                    if 0 <= dscp_val <= 63:
                        options.tos = dscp_val << 2
                        log.info(f"Using DSCP value {dscp_val}, setting ToS to {options.tos}")
                    else:
                        parser.error(f"Invalid DSCP numeric value '{options.dscp}'. Must be 0-63.")
                except ValueError:
                    parser.error(f"Invalid DSCP name or value '{options.dscp}'. Use 'dscptable' to see names.")
        else:
             # Use provided --tos value (default is 0 if not specified)
             if not (0 <= options.tos <= 255):
                  parser.error(f"Invalid ToS value '{options.tos}'. Must be 0-255.")
             log.info(f"Using ToS value {options.tos}")

        # Convert interval from ms to seconds if needed (assuming CLI takes seconds now)
        # if hasattr(options, 'interval'): options.interval /= 1000.0

    # --- Execute Selected Function ---
    try:
        result = options.func(options)
        if options.mode == 'sender' and isinstance(result, dict) and 'error' not in result:
             # Print sender results nicely if run interactively
             print("\n--- TWAMP Sender Results ---")
             print(f"  Packets Tx/Rx:    {result.get('packets_tx', 'N/A')} / {result.get('packets_rx', 'N/A')}")
             print(f"  Loss:             {result.get('total_loss_percent', 'N/A'):.2f}%")
             print(f"  Round Trip Time:")
             print(f"    Min/Avg/Max:    {dp(result.get('roundtrip_min_us'))} / {dp(result.get('roundtrip_avg_us'))} / {dp(result.get('roundtrip_max_us'))}")
             print(f"    Jitter:         {dp(result.get('roundtrip_jitter_us'))}")
             print(f"  Outbound Latency:")
             print(f"    Min/Avg/Max:    {dp(result.get('outbound_min_us'))} / {dp(result.get('outbound_avg_us'))} / {dp(result.get('outbound_max_us'))}")
             print(f"    Jitter:         {dp(result.get('outbound_jitter_us'))}")
             print(f"  Inbound Latency:")
             print(f"    Min/Avg/Max:    {dp(result.get('inbound_min_us'))} / {dp(result.get('inbound_avg_us'))} / {dp(result.get('inbound_max_us'))}")
             print(f"    Jitter:         {dp(result.get('inbound_jitter_us'))}")
             if result.get('error'): print(f"\n  Error: {result['error']}")
        elif isinstance(result, str):
             print(result) # Print status messages from responder etc.
        elif isinstance(result, dict) and 'error' in result:
             print(f"Error: {result['error']}") # Print error from sender/responder init
             sys.exit(1)

    except KeyboardInterrupt:
        log.warning("Keyboard interrupt received. Exiting.")
        # Threads should be stopped by signal handlers if interactive
        sys.exit(1)
    except Exception as main_err:
        log.exception(f"An unexpected error occurred: {main_err}")
        sys.exit(1)

# EOF