# Blender viewport

Opens the viewport in its own Blender window, reveals the sidebar, and selects
the Flexible Drawing tab. Two editors host the viewport: the Image Editor, which
shows the canvas flat, and the native 3D View, which places it in the scene.

Blender creates a sidebar's tab list only after the first redraw. The extension
therefore retries tab selection until the new window has been drawn.

This package also converts screen positions to canvas coordinates. The Image
Editor conversion works today because Blender already provides its pan and zoom
mapping. The 3D View can show the sidebar, but pointer conversion is not
implemented because it also needs a canvas plane and a view ray.

Canvas drawing remains the responsibility of the canvas execution and
presentation providers.
