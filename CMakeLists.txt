# Whether the Blender host integration is expected is this repository's own switch, under its own
# name. An embedder says so in its terms before adding this directory.
option(BLENDER_PLUGIN_ENABLE_HOST "The Blender host integration is expected to be implemented" OFF)

add_subdirectory(fd_plugin)

# Blender-specific composition root. It does not depend on the default native
# application because that composition selects the LightRHI canvas provider.
flexible_drawing_add_boundary(flexible_drawing_blender_plugin FlexibleDrawing::BlenderPlugin
  FlexibleDrawing::UseCases FlexibleDrawing::Presentation FlexibleDrawing::HostBlender
  FlexibleDrawing::HostAbi FlexibleDrawing::HostBlenderUsd
  FlexibleDrawing::HostBlenderHydra FlexibleDrawing::CanvasProviderOnBlender
)
