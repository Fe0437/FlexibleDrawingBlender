# Blender document binding

A document binding lets Blender remember which engine document it represents.
It stores the document identity and revision in Blender ID properties.

Blender objects and pointers remain in the extension. They never cross the C
interface or become part of an engine document.
