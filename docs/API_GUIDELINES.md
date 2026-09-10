# API guidelines

<!-- BEGIN SHARED API GUIDELINES -->
## Shared API rules

This section is copied unchanged across the first-party source repositories.
Rules specific to this repository follow it.

### Publish the intended contract

An exported API represents a stable concept, not the current folder layout or
backend implementation. Choose the smallest declaration that lets a caller use
the concept correctly.

Do not publish a temporary name, signature, record, or package boundary when the
intended shape is already known. If a declaration must remain provisional, state
its current limitation, the kind of change expected, and what callers must not
rely on. Do not use an issue or milestone as that explanation.

### Use consistent names

| Category | Convention |
| --- | --- |
| C++ module | lowercase dotted name |
| C++ namespace | lowercase `snake_case` |
| Exported type, enum value, function, or method | `PascalCase` |
| Abstract interface | `I` + `PascalCase` |
| Public aggregate field | `PascalCase` |
| Private member or helper | `_camelCase` |
| Local or parameter | `lowerCamelCase` |
| File or directory | `snake_case` |

Use the domain noun that tells a reader what a value represents. Avoid generic
names such as `Config`, `Data`, `Info`, `Manager`, `Helper`, or `Utility`.

Use these suffixes consistently:

- `Settings` for policy retained across operations;
- `Desc` for complete input to one create, build, or execute operation;
- `Params` for domain or mathematical values used by a computation;
- `State` for mutable values with an explicit lifecycle;
- `Snapshot` for immutable values observed at one time;
- `Configuration` for a named selection of already-defined interchangeable parts.

A private function name must state its concrete operation and any important state
it changes. Do not hide mutation behind vague verbs such as `prepare`, `process`,
`handle`, or `update` when the signature does not expose the result.

### Prefer explicit values and ownership

Use brace initialization for every C++ variable and object. Keep `=` for
assignment, aliases, default arguments, enum values, and deleted or defaulted
functions. Use designated initializers for descriptor and schema aggregates.

Use a value type when data has no hidden lifetime or invariant. Use a class when
it protects an invariant, owns behavior, or manages a resource. Prefer one
descriptor value to a long parameter list. Do not add a field without a concrete
use.

Use RAII and standard smart pointers for ownership. Do not use raw `new` or
`delete`. The one exception is a factory whose constructor is private, so that
the factory is the only way to build the object: it may pass `new` straight into
the `std::unique_ptr` it returns, with a comment saying why. Use references for required borrowed objects and plain pointers only
when null is meaningful. Use `gsl::not_null` when pointer syntax is required but
null is not valid. Use `std::span` for synchronous borrowed contiguous sequences.
Use `T&&` only when the callee takes ownership.

Return `std::expected<T, E>` for recoverable C++ failures. Use a domain
`enum class` when one module owns the closed failure set, or a stable typed token
when several modules may add failures. Do not return bare strings or untyped
integers as errors. Contain third-party exceptions at the integration boundary
and translate them before they cross a project API.

Validate externally chosen counts, sizes, offsets, strides, and arithmetic before
allocation, mapping, or copying.

### Keep contracts cohesive

A package should have one reason to change. Split a responsibility when the new
part has a different lifecycle, forms a useful contract, or keeps a volatile
dependency from moving inward. Do not split cohesive implementation steps merely
to shorten a file.

An interface lives with the stable concept that owns the contract. Avoid generic
packages named `types`, `interfaces`, `common`, `helpers`, `utilities`, or
`adapters`. Use inheritance only for a real runtime boundary; otherwise prefer
composition, tagged values, or variants.

Dependencies point toward stable contracts. Platform, framework, backend, and
transport types stay inside their integration boundary unless the public contract
is specifically about that external system.

### Document the public API

Start every C or C++ source with a `{file}` and `{brief}` block that states its
responsibility and the nearest work outside it. Document every exported type,
enum value, aggregate field, function, and public method at its declaration.

Write from the caller's point of view. State units, valid ranges, ownership,
lifetime, mutation, call order, synchronization, and failure behavior when they
matter. Use short sentences and ordinary words.

Use `{brief}`, `{param name}`, `{tparam name}`, `{returns}`, `{note}`,
`{warning}`, `{pre}`, and `{post}`. A field description stays on the same line
after `///<` when it is short.

### Keep changes reviewable

Use the repository formatter and static-analysis configuration. Do not hand-format
around them. Never edit generated files by hand.

A public signature, exported value, error, ownership rule, or package-boundary
change requires corresponding documentation and contract-test review. Add no
dependency, abstraction, fallback path, or compatibility layer without a concrete
current requirement.
<!-- END SHARED API GUIDELINES -->

The following rules add the constraints of the Blender boundary.

## Keep Blender objects inside the host edge

Do not pass `bpy` objects, RNA wrappers, Python object addresses, or Blender SDK
types through the C ABI. Convert them to documented values first.

The ABI package must not import `bpy`. Presentation and host packages may use
it because they run inside Blender.

## Treat the C ABI as versioned input

Load the function table through its published entry point. Check the ABI
version and table size before reading optional fields. Never infer support from
the installed extension version alone.

Native handles are opaque values owned by the engine. Python code may store and
compare them, but must not manufacture them or use them after engine shutdown.

## Make ownership visible

Every function that receives a Blender object must state whether it reads it
during the call or stores a stable identifier. Do not retain borrowed event or
context objects.

Registration and unregistration must be symmetric and safe across repeated
enable and disable cycles. Release Blender callbacks before releasing the ABI
client they call.

## Name host operations precisely

Use the Blender concept and the effect in private names. Names such as
`_convertImageEditorEventToInputSample` or `_releaseDocumentReceiver` are
preferable to `_prepare`, `_process`, or `_cleanup`.
