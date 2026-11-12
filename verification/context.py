"""Shared data, transport conversion and explicit DWARF register mappings.

This module never decodes expressions or implements DWARF operations.
"""
import re


def validate(context, width):
    from run import prepare_context
    if not isinstance(context, dict) or set(context) - {"initial_stack", "registers", "register_widths", "memory", "memory_requests", "types", "raw_types", "wasm_locations", "cfa", "framebase", "debug_addr", "debug_addr_load_bias", "object_address", "dwarf_offset_size", "compilation_unit_offset", "die_locations", "entry_context", "tls_addresses", "address_spaces"}:
        raise ValueError("invalid shared context fields")
    prepare_context({"address_width": width, "endianness": "little", **context})


def registers(width, target=None):
    """DWARF number -> (name, RSP number), for address-sized x86 GPRs/PC.

    AMD64 DWARF order differs from its remote packet order (notably rdx/rbx).
    Vector, x87, segment and flags registers are deliberately outside this map.
    """
    if target == "aarch64":
        return {**{i: (f"x{i}", i) for i in range(31)}, 31: ("sp", 31), 32: ("pc", 32)}
    if width == 32:
        names = "eax ecx edx ebx esp ebp esi edi eip".split()
        return {i: (name, i) for i, name in enumerate(names)}
    names = "rax rdx rcx rbx rsi rdi rbp rsp r8 r9 r10 r11 r12 r13 r14 r15 rip".split()
    remote = "rax rbx rcx rdx rsi rdi rbp rsp r8 r9 r10 r11 r12 r13 r14 r15 rip".split()
    return {i: (name, remote.index(name)) for i, name in enumerate(names)}

