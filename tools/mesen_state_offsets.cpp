// superforge — provenance for the ctypes struct mirrors in vendor/mesen_runner.py.
//
// vendor/mesen_runner.py reaches the SNES DMA controller's real registers (and
// the live NMITIMEN) through the DLL's GetConsoleState export, which memcpy's a
// whole `SnesState` into a caller-owned buffer. `SnesState` is a plain C++
// aggregate with no stable ABI, so the byte offsets in mesen_runner.py are
// DERIVED, not guessed — this file is how they were derived, kept so the next
// agent can re-derive them in one command instead of counting struct members.
//
// It is NOT part of the build and NOT a test dependency: the runner validates
// the layout structurally at every read (_validate_snes_state_layout) and the
// suite anchors it on an independently-predicted value
// (tests/test_decl_impl_channels.py::test_console_state_layout_anchor). Run
// this only when that validation fires, or when bumping the vendored Mesen2.
//
// Build + run (needs the Mesen2 source tree tools/setup.sh clones to /tmp):
//
//   g++ -std=c++17 -I/tmp/Mesen2/Core -I/tmp/Mesen2/Utilities -I/tmp/Mesen2 \
//       -include /tmp/Mesen2/Core/pch.h tools/mesen_state_offsets.cpp \
//       -o /tmp/mesen_state_offsets && /tmp/mesen_state_offsets
//
// Expected output for the Mesen2 revision this repo pins (2026-07-27):
//
//   sizeof(SnesState)                 = 1440
//   offsetof(SnesState, Cpu)          = 8      + offsetof(SnesCpuState, A) = 16
//   offsetof(SnesState, Dma)          = 1238
//   offsetof(SnesState, InternalRegs) = 1400
//   sizeof(DmaChannelConfig)          = 20
//   offsetof(SnesDmaControllerState, HdmaChannels) = 160
//   sizeof(Breakpoint)                = 1028
//   SnesCpuState, relative to offsetof(A):
//     A=0 X=2 Y=4 SP=6 D=8 PC=10 K=12 DBR=13 PS=14 EmulationMode=15
//     IrqLock=17 NeedNmi=18 StopState=21
//
// `#define private public` is a deliberate hack: Breakpoint's fields are
// private and offsetof on them will not compile otherwise. This file never
// links against the core, so the hack cannot leak anywhere.
#define private public
#include "Debugger/Breakpoint.h"
#undef private
#include "SNES/SnesState.h"
#include "Debugger/DebugTypes.h"
#include "Shared/MemoryType.h"
#include <cstddef>
#include <cstdio>

int main()
{
	printf("sizeof(SnesState)                 = %zu\n", sizeof(SnesState));
	printf("offsetof(SnesState, Cpu)          = %zu\n", offsetof(SnesState, Cpu));
	printf("  + offsetof(SnesCpuState, A)     = %zu\n",
		offsetof(SnesState, Cpu) + offsetof(SnesCpuState, A));
	printf("offsetof(SnesState, Dma)          = %zu\n", offsetof(SnesState, Dma));
	printf("offsetof(SnesState, InternalRegs) = %zu\n", offsetof(SnesState, InternalRegs));
	printf("sizeof(SnesDmaControllerState)    = %zu\n", sizeof(SnesDmaControllerState));
	printf("sizeof(DmaChannelConfig)          = %zu\n", sizeof(DmaChannelConfig));
	printf("offsetof(..., HdmaChannels)       = %zu\n",
		offsetof(SnesDmaControllerState, HdmaChannels));

	printf("\nSnesCpuState fields (all RELATIVE to offsetof(A), which is what\n"
	       "mesen_runner.py's _OFF_SNES_CPU_A pins):\n");
	printf("  A=%zu X=%zu Y=%zu SP=%zu D=%zu PC=%zu\n",
		offsetof(SnesCpuState, A) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, X) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, Y) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, SP) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, D) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, PC) - offsetof(SnesCpuState, A));
	printf("  K=%zu DBR=%zu PS=%zu EmulationMode=%zu\n",
		offsetof(SnesCpuState, K) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, DBR) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, PS) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, EmulationMode) - offsetof(SnesCpuState, A));
	printf("  IrqLock=%zu NeedNmi=%zu StopState=%zu\n",
		offsetof(SnesCpuState, IrqLock) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, NeedNmi) - offsetof(SnesCpuState, A),
		offsetof(SnesCpuState, StopState) - offsetof(SnesCpuState, A));

	printf("\nDmaChannelConfig fields:\n");
	printf("  SrcAddress=%zu TransferSize=%zu HdmaTableAddress=%zu SrcBank=%zu\n",
		offsetof(DmaChannelConfig, SrcAddress), offsetof(DmaChannelConfig, TransferSize),
		offsetof(DmaChannelConfig, HdmaTableAddress), offsetof(DmaChannelConfig, SrcBank));
	printf("  DestAddress=%zu DmaActive=%zu InvertDirection=%zu Decrement=%zu\n",
		offsetof(DmaChannelConfig, DestAddress), offsetof(DmaChannelConfig, DmaActive),
		offsetof(DmaChannelConfig, InvertDirection), offsetof(DmaChannelConfig, Decrement));
	printf("  FixedTransfer=%zu HdmaIndirectAddressing=%zu TransferMode=%zu\n",
		offsetof(DmaChannelConfig, FixedTransfer),
		offsetof(DmaChannelConfig, HdmaIndirectAddressing),
		offsetof(DmaChannelConfig, TransferMode));
	printf("  HdmaBank=%zu HdmaLineCounterAndRepeat=%zu DoTransfer=%zu\n",
		offsetof(DmaChannelConfig, HdmaBank),
		offsetof(DmaChannelConfig, HdmaLineCounterAndRepeat),
		offsetof(DmaChannelConfig, DoTransfer));
	printf("  HdmaFinished=%zu UnusedControlFlag=%zu UnusedRegister=%zu\n",
		offsetof(DmaChannelConfig, HdmaFinished),
		offsetof(DmaChannelConfig, UnusedControlFlag),
		offsetof(DmaChannelConfig, UnusedRegister));

	printf("\nInternalRegisterState (size %zu):\n", sizeof(InternalRegisterState));
	printf("  EnableAutoJoypadRead=%zu EnableFastRom=%zu EnableNmi=%zu\n",
		offsetof(InternalRegisterState, EnableAutoJoypadRead),
		offsetof(InternalRegisterState, EnableFastRom),
		offsetof(InternalRegisterState, EnableNmi));
	printf("  EnableHorizontalIrq=%zu EnableVerticalIrq=%zu HorizontalTimer=%zu\n",
		offsetof(InternalRegisterState, EnableHorizontalIrq),
		offsetof(InternalRegisterState, EnableVerticalIrq),
		offsetof(InternalRegisterState, HorizontalTimer));
	printf("  VerticalTimer=%zu IoPortOutput=%zu ControllerData=%zu\n",
		offsetof(InternalRegisterState, VerticalTimer),
		offsetof(InternalRegisterState, IoPortOutput),
		offsetof(InternalRegisterState, ControllerData));

	printf("\nsizeof(Breakpoint)                = %zu\n", sizeof(Breakpoint));
	printf("  _id=%zu _cpuType=%zu _memoryType=%zu _type=%zu\n",
		offsetof(Breakpoint, _id), offsetof(Breakpoint, _cpuType),
		offsetof(Breakpoint, _memoryType), offsetof(Breakpoint, _type));
	printf("  _startAddr=%zu _endAddr=%zu _enabled=%zu _markEvent=%zu\n",
		offsetof(Breakpoint, _startAddr), offsetof(Breakpoint, _endAddr),
		offsetof(Breakpoint, _enabled), offsetof(Breakpoint, _markEvent));
	printf("  _ignoreDummyOperations=%zu _condition=%zu\n",
		offsetof(Breakpoint, _ignoreDummyOperations),
		offsetof(Breakpoint, _condition));
	return 0;
}
