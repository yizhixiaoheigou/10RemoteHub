# Unified receiver collector (macOS 13+)

Product composition is **main App + device collector + optional virtual microphone**.
This component collects both key reports and encoded voice from USB `0416:0602`.
There is no separate audio helper, GUI, sudo terminal or additional audio authorization.
The GUI parses HID, decodes G.722.1, executes mappings and feeds the microphone.

`Daemon.m` is the collector's launchd/XPC entry point; `Capture.c` is its native USB
worker. They are one installed component. The short-lived child isolates the USB
lifetime and can restore the drivers when its parent exits. This is an internal
process boundary, not another user-installable product or permission step.

## Trust and lifecycle

- Both XPC peers pin the build's signing certificate (leaf SHA-1) and exact
  identifiers. Release builds use the project's own "10RemoteHub" certificate,
  so no Apple Team ID is needed; an Apple-issued certificate works the same way. Only the current non-root console user may connect; one owner.
- Root-owned binaries and the bundled libusb are checked before launch. No shell,
  configurable executable, arbitrary file path, arbitrary VID/PID or USB command
  is accepted over XPC. The only controls are connect, heartbeat, start/stop
  recording and disconnect. GUI stays unprivileged.
- macOS capture detaches the whole receiver once. All 5 interfaces are claimed;
  key descriptors/reports and encoded voice use the same bounded event stream.
  Unsupported layouts are rejected before capture. A receiver `01 82 03`
  request is acknowledged to prevent re-enumeration; microphone data reaches the
  GUI only after the main App attaches audio. If the virtual microphone is not
  ready, the App closes that vendor session immediately instead of dropping keys.
  macOS stop uses the hardware-verified `01 01 00 00` command (the Windows
  collector has its own `01 00` stop path; the two are not interchangeable).
- The daemon uses a GCD main queue, bounded nonblocking pipe reads, serialized
  descriptor closure and per-callback autorelease pools. Small key/ready messages
  are forwarded immediately rather than waiting to fill a buffer.
- The client sends heartbeats every 2 seconds on an independent native GCD queue,
  not a GUI/Python timer. Disconnect, failure and queue overflow cancel the timer.
  A native fixture stalls the main thread for 6.5 seconds and checks continued
  beats, cancellation and failure cleanup without connecting any real service.
- A 6-second heartbeat lease, bounded event queues, connection invalidation and
  console-user changes stop capture. Normal stop waits for child exit; the worker
  restores drivers on exit, cancellation and partial claim failures. If USB calls
  hang, the daemon force-stops the child after 3 seconds; physical unplug/replug
  may still be needed. No claim of guaranteed restoration after SIGKILL.
- Input Monitoring is no longer used to gate this raw USB path. Accessibility is
  still needed in the main App to execute keyboard/window mappings. Diagnostics
  from an SSH-launched App must not be confused with the GUI's TCC status.

## Build / install

`scripts/build_device_helper.py --codesign-identity <identity>` derives the
certificate hash from the signed worker, builds the native bridge and creates install/uninstall
packages. It uses the build machine's existing Homebrew libusb; the dylib and
COPYING license are bundled, and runtime does not require Homebrew or Python.
`--adhoc` builds a bridge that refuses privileged connection and emits no packages.
The full App builder includes both packages; the unified setup offers the collector
alongside the main App, with the virtual microphone optional and unchecked.

Only the system Installer runs package scripts. Building, checking status or
opening the App does not install/register services. Installed paths are limited to:

- `/Library/PrivilegedHelperTools/10RemoteHub/` (collector, worker, libusb, license)
- `/Library/LaunchDaemons/org.remotehub.device-helper.plist`

Uninstall removes exactly those files and the service; it does not delete mappings,
App, microphone or TCC records. `SMAppService` is not used for this development
package because the local SDK requires notarization for LaunchDaemons; release
notarization/signing is still separate work.

## Verification boundary

Native warning-clean compile, fake USB state-machine tests, native unsigned
refusal, package payload/ownership/script inspection, Python routing/lifecycle
regressions and offscreen UI checks do not prove real XPC trust, privileged
installation, receiver capture or end-to-end speech recognition. Those require
the locally signed App and explicit installation/hardware testing.

2026-11-05 hardware check: signed XPC and worker launch succeeded. Interface 0
returns its declared 32-byte HID report descriptor, but stalls a 1024-byte
request. The collector now reads each report length from its HID descriptor,
requests exactly that size and rejects short reads. The signed fix was installed and the physical number-1 key reached the App
action dispatcher. Full key and voice acceptance remains pending. The fake USB fixture enforces the
exact-length behavior and verifies driver restoration after a short read.

Upgrade scripts wait up to ten seconds for bootout to remove the previous job
before replacing files. launchd allows six seconds for the daemon's four-second
USB cleanup. Immediate bootstrap after asynchronous bootout was observed to fail
with operation-already-in-progress on 2026-11-05; shell fixtures cover delayed
removal and aborting on timeout.

The collector now keeps one asynchronous read armed on each IN endpoint with
no transfer timeout. Completed packets are copied and the read is re-armed before
processing key reports or voice commands. Transfers use fixed 64-byte buffers;
shutdown cancels reads and waits for callbacks before freeing them or releasing
interfaces. If cancellation does not finish in two seconds, the process exits
without freeing live transfers; unplug/replug may be required.

Evidence: the old 2ms round-robin reader emitted presses but no releases. A
250ms keyboard-only reader received three complete short presses but still
missed the final long-press release. Preserving timeout data alone did not fix
hardware behavior. Transient error/cancelled completions are re-armed in the same process with a 100 ms retry interval, avoiding detach/reopen storms; NO_DEVICE and other fatal failures still stop capture. It is covered by simulated concurrent
key/voice, long hold/repeat, partial submit failure, resubmit failure, transient recovery, repeated-error, disconnect
and cleanup cases. Hardware log `20261105-135002-continuous.jsonl` confirms eight
number-1 presses and eight releases, including holds of 1.14–1.919 seconds and
no key remaining held. Full multi-key/voice acceptance is tracked separately.
No synthetic releases or changes to GUI repeat suppression are used.

A receiver `01 86` inactive state ends keepalives and closes the voice session;
the receiver can emit it before the corresponding HID key release. This is not
classified as a USB read failure. Control diagnostics contain only the four-byte
command/status prefix, not the audio payload. A delayed re-enumeration keeps the
GUI recovery request pending until the receiver is visible again.

The product limits each physical voice-key recording and recognition wake to
60 seconds. Expiry closes the session normally, restores the previous default
microphone and does not start another take while the key remains held. It is not
reported as a USB failure. macOS keeps its verified `01 01 00 00` stop command;
Windows retains its own stop path. WAV file playback tests are not recordings
and do not use this one-minute limit.

API basis: [libusb asynchronous I/O](https://libusb.sourceforge.io/api-1.0/group__libusb__asyncio.html)
and the [Darwin cancellation implementation](https://github.com/libusb/libusb/blob/master/libusb/os/darwin_usb.c).
