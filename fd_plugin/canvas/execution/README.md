# Canvas execution in Blender

This dab-based raster canvas execution applies dabs and reports what changed. This future
implementation will apply groups of dabs through Blender's GPU API. It will not
call Python once per input sample or GPU command.

It is one Blender output provider. Geometry and other Blender integrations use
their own domain contracts and do not pass through this canvas API.

Work that Blender cannot perform will return a list of the missing features.
