"""Cases describe fixtures; observations describe what actually happened."""
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Case:
    id: str
    bytes: list
    address_width: int
    endianness: str
    dwarf_version: int
    delegate: bool
    object_size: int
    origin: dict
    compare: list
    expected: dict = field(default_factory=dict)
    requirements: list = field(default_factory=list)
    backends: list = field(default_factory=lambda: ["k", "lldb", "gdb"])
    # None preserves the original no-process fixture; {} supplies an empty one.
    context: dict | None = None
    architecture: str | None = None
    object_bit_size: int | None = None
    object_format: str = "integer"
    # Explicitly reproduce LLDB unit-test delegates without fabricating a CU.
    lldb_type_source: str = "module"
    # Source assertions checked against K, independently of debugger comparisons.
    upstream_assertions: list = field(default_factory=list)
    purpose: str = "location"
    dependencies: list = field(default_factory=list)

    def document(self):
        result = asdict(self)
        for key in ("architecture", "object_bit_size"):
            if result[key] is None:
                result.pop(key)
        if self.object_format == "integer":
            result.pop("object_format")
        if self.lldb_type_source == "module":
            result.pop("lldb_type_source")
        if self.context is None:
            result.pop("context")
        if not self.upstream_assertions:
            result.pop("upstream_assertions")
        if self.purpose == "location":
            result.pop("purpose")
        if not self.dependencies:
            result.pop("dependencies")
        return result


@dataclass
class Observation:
    backend: str
    state: str
    kind: str = "unknown"
    integer: str | None = None
    bits: str | None = None
    width: int | None = None
    type_identity: str | None = None
    diagnostic: str = ""
    native: dict = field(default_factory=dict)
    assertion: dict = field(default_factory=dict)
    # A DWARF register identity, never its contents; decimal string on the wire.
    register: str | None = None
    # Raw object bits and availability are separate evidence. None is not a known mask.
    object_bits: str | None = None
    availability: str | None = None
    pieces: list | None = None

    def document(self):
        return asdict(self)
