# Blender integration targets are owned by the Blender extension subproject.
# Blender SDK types never cross these boundaries into shared source layers.
flexible_drawing_add_boundary(flexible_drawing_host_blender FlexibleDrawing::HostBlender
  FlexibleDrawing::UseCases FlexibleDrawing::Presentation)

foreach(package IN ITEMS Host Lifecycle Scene Input Viewport Geometry GreasePencil Texture DocumentBinding)
  string(REGEX REPLACE "([a-z0-9])([A-Z])" "\\1_\\2" package_target "${package}")
  string(TOLOWER "${package_target}" package_target)
  flexible_drawing_add_boundary("flexible_drawing_host_blender_${package_target}"
    "FlexibleDrawing::HostBlender${package}" FlexibleDrawing::HostBlender)
endforeach()

flexible_drawing_add_boundary(flexible_drawing_canvas_execution_on_blender
  FlexibleDrawing::CanvasExecutionOnBlender FlexibleDrawing::HostBlender
  FlexibleDrawing::CanvasExecution)
flexible_drawing_add_boundary(flexible_drawing_canvas_presentation_on_blender
  FlexibleDrawing::CanvasPresentationOnBlender FlexibleDrawing::HostBlender
  FlexibleDrawing::CanvasPresentation)
flexible_drawing_add_boundary(flexible_drawing_canvas_provider_on_blender
  FlexibleDrawing::CanvasProviderOnBlender FlexibleDrawing::CanvasExecutionOnBlender
  FlexibleDrawing::CanvasPresentationOnBlender)

flexible_drawing_add_boundary(flexible_drawing_host_blender_usd FlexibleDrawing::HostBlenderUsd
  FlexibleDrawing::HostBlender FlexibleDrawing::SceneUsdCompatibility)
flexible_drawing_add_boundary(flexible_drawing_host_blender_hydra FlexibleDrawing::HostBlenderHydra
  FlexibleDrawing::HostBlender FlexibleDrawing::RenderHydra)

if(BLENDER_PLUGIN_ENABLE_HOST)
  message(FATAL_ERROR "host.blender is a prepared boundary but has no implementation yet")
endif()
