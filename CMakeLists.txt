add_subdirectory(fd_plugin)

# Blender-specific composition root. It does not depend on the default native
# application because that composition selects the LightRHI canvas provider.
flexible_drawing_add_boundary(flexible_drawing_blender_plugin FlexibleDrawing::BlenderPlugin
  FlexibleDrawing::UseCases FlexibleDrawing::Presentation FlexibleDrawing::HostBlender
  FlexibleDrawing::HostAbi FlexibleDrawing::HostBlenderUsd
  FlexibleDrawing::HostBlenderHydra FlexibleDrawing::CanvasProviderOnBlender
)
