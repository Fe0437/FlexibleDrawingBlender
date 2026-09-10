# The parent project supplies the native ABI library and the shared test harness. The behavior
# exercised here belongs to the Blender extension, so the test source stays with that submodule.
#
# Which Blender to drive, and whether to run the smoke that opens a window, are this repository's
# own switches under its own names. Whoever adds this directory says so in its terms; these tests
# can be added without the extension's own directory, so they are declared here.
set(BLENDER_PLUGIN_EXECUTABLE "" CACHE FILEPATH "Supported Blender executable these smokes drive")
option(BLENDER_PLUGIN_INTERACTIVE "Run the smoke that opens a window and simulates pointer input" OFF)
set(BLENDER_PLUGIN_WHEEL_DIR "" CACHE PATH "Python wheels, and their licence notices, the extension bundles")

add_library(flexible_drawing_blender_ui_schema_fixture)
flexible_drawing_add_modules(flexible_drawing_blender_ui_schema_fixture .)
target_link_libraries(flexible_drawing_blender_ui_schema_fixture PUBLIC flexible_drawing_ui_schema_fixtures)
flexible_drawing_set_warnings(flexible_drawing_blender_ui_schema_fixture)
flexible_drawing_apply_enabled_sanitizers(flexible_drawing_blender_ui_schema_fixture)

add_executable(flexible_drawing_blender_ui_schema_contract_test ui_schema_blender_contract.cpp)
target_link_libraries(flexible_drawing_blender_ui_schema_contract_test PRIVATE flexible_drawing_blender_ui_schema_fixture)
flexible_drawing_set_warnings(flexible_drawing_blender_ui_schema_contract_test)
flexible_drawing_apply_enabled_sanitizers(flexible_drawing_blender_ui_schema_contract_test)

flexible_drawing_add_test(
  NAME flexible_drawing.blender_ui_schema_contract
  COMMAND $<TARGET_FILE:flexible_drawing_blender_ui_schema_contract_test>
  LABELS unit contract blender presentation schema
  TIMEOUT 30
  SEED 0
  FIXTURES_REQUIRED flexible_drawing_test_environment)

# Every test below loads the engine library into Python or Blender. ThreadSanitizer must already run
# in a process that loads an instrumented library, and neither host can start it, so a
# ThreadSanitizer build leaves them out; the engine's threads are checked by its own C++ tests.
if(FLEXIBLE_DRAWING_ENABLE_TSAN)
  return()
endif()

flexible_drawing_add_test(
  NAME flexible_drawing.blender_plugin
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test_blender_plugin.py"
    --project-source-dir "${PROJECT_SOURCE_DIR}"
    --extension-dir "${CMAKE_CURRENT_SOURCE_DIR}/../extension"
    --library $<TARGET_FILE:flexible_drawing_host_abi>
  LABELS unit blender package
  TIMEOUT 30
  SEED 0
  FIXTURES_REQUIRED flexible_drawing_test_environment)

flexible_drawing_add_test(
  NAME flexible_drawing.blender_ui_projection
  COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test_blender_ui_projection.py"
    --project-source-dir "${PROJECT_SOURCE_DIR}"
    --extension-dir "${CMAKE_CURRENT_SOURCE_DIR}/../extension"
  LABELS unit blender presentation schema
  TIMEOUT 30
  SEED 0
  FIXTURES_REQUIRED flexible_drawing_test_environment)

# The extension's Realtime Plane client speaks the profile the Realtime Plane speaks; the profile's
# own directory is where both read it from.
if(TARGET FlexibleDrawing::RealtimePlaneProtocol)
  get_target_property(blender_plugin_profile_dir FlexibleDrawing::RealtimePlaneProtocol SOURCE_DIR)
  flexible_drawing_add_test(
    NAME flexible_drawing.blender_realtime_plane_session
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test_realtime_plane_session.py"
      --extension-dir "${CMAKE_CURRENT_SOURCE_DIR}/../extension"
      --protocol-dir "${blender_plugin_profile_dir}"
    LABELS unit blender realtime_plane ipc
    TIMEOUT 30
    SEED 0
    FIXTURES_REQUIRED flexible_drawing_test_environment)
endif()

# A Realtime Plane that paints with a fake pen and needs no window: the Realtime Plane's own
# host-session peer, behind the Realtime Plane's command line.
set(blender_plugin_stand_in OFF)
if(BLENDER_PLUGIN_WHEEL_DIR AND TARGET flexible_drawing_realtime_plane_host_session_peer)
  set(blender_plugin_stand_in ON)
  flexible_drawing_add_test(
    NAME flexible_drawing.blender_realtime_plane_link
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test_realtime_plane_link.py"
      --extension-dir "${CMAKE_CURRENT_SOURCE_DIR}/../extension"
      --protocol-dir "${blender_plugin_profile_dir}"
      --peer $<TARGET_FILE:flexible_drawing_realtime_plane_host_session_peer>
      --wheel-dir "${BLENDER_PLUGIN_WHEEL_DIR}"
    LABELS integration blender realtime_plane ipc
    TIMEOUT 180
    SEED 0
    FIXTURES_REQUIRED flexible_drawing_test_environment)
endif()

if(BLENDER_PLUGIN_EXECUTABLE)
  if(blender_plugin_stand_in)
    flexible_drawing_add_test(
      NAME flexible_drawing.blender_realtime_plane
      COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test_blender_realtime_plane.py"
        --blender "${BLENDER_PLUGIN_EXECUTABLE}"
        --package-script "${PROJECT_SOURCE_DIR}/tools/blender/package.py"
        --extension-dir "${CMAKE_CURRENT_SOURCE_DIR}/../extension"
        --library $<TARGET_FILE:flexible_drawing_host_abi>
        --wheel-dir "${BLENDER_PLUGIN_WHEEL_DIR}"
        --peer $<TARGET_FILE:flexible_drawing_realtime_plane_host_session_peer>
      LABELS blender integration realtime_plane
      TIMEOUT 240
      SEED 0
      FIXTURES_REQUIRED flexible_drawing_test_environment)
  endif()

  flexible_drawing_add_test(
    NAME flexible_drawing.blender_lifecycle_smoke
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/blender/smoke_driver.py"
      --source "${PROJECT_SOURCE_DIR}"
      --library $<TARGET_FILE:flexible_drawing_host_abi>
      --executable "${BLENDER_PLUGIN_EXECUTABLE}"
    LABELS smoke blender integration
    TIMEOUT 90
    SEED 0
    FIXTURES_REQUIRED flexible_drawing_test_environment)

  flexible_drawing_add_test(
    NAME flexible_drawing.blender_incompatible_runtime_smoke
    COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/blender/smoke_driver.py"
      --source "${PROJECT_SOURCE_DIR}"
      --library $<TARGET_FILE:flexible_drawing_host_abi>
      --executable "${BLENDER_PLUGIN_EXECUTABLE}"
      --script "${PROJECT_SOURCE_DIR}/tools/blender/incompatible_runtime_smoke.py"
      --cycles 1
      --success-marker FLEXIBLE_DRAWING_INCOMPATIBLE_RUNTIME_OK
    LABELS smoke blender integration negative
    TIMEOUT 90
    SEED 0
    FIXTURES_REQUIRED flexible_drawing_test_environment)

  if(BLENDER_PLUGIN_WHEEL_DIR)
    flexible_drawing_add_test(
      NAME flexible_drawing.blender_extension_wheels
      COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test_bundled_wheels.py"
        --package-script "${PROJECT_SOURCE_DIR}/tools/blender/package.py"
        --extension-dir "${CMAKE_CURRENT_SOURCE_DIR}/../extension"
        --library $<TARGET_FILE:flexible_drawing_host_abi>
        --wheel-dir "${BLENDER_PLUGIN_WHEEL_DIR}"
        --blender "${BLENDER_PLUGIN_EXECUTABLE}"
        --output "${CMAKE_CURRENT_BINARY_DIR}/blender-extension-wheels.json"
      LABELS blender integration package
      TIMEOUT 90
      SEED 0
      FIXTURES_REQUIRED flexible_drawing_test_environment)
  endif()

  # This opens a real Blender window and waits on Blender's event loop. Keep it out of the smoke
  # gate and require a caller that explicitly declares an interactive desktop session.
  if(BLENDER_PLUGIN_INTERACTIVE)
    flexible_drawing_add_test(
      NAME flexible_drawing.blender_paint_interaction
      COMMAND "${Python3_EXECUTABLE}" "${PROJECT_SOURCE_DIR}/tools/blender/smoke_driver.py"
        --source "${PROJECT_SOURCE_DIR}"
        --library $<TARGET_FILE:flexible_drawing_host_abi>
        --executable "${BLENDER_PLUGIN_EXECUTABLE}"
        --script "${PROJECT_SOURCE_DIR}/tools/blender/paint_interaction.py"
        --cycles 1
        --success-marker FLEXIBLE_DRAWING_PAINT_INTERACTION_OK
        --interactive
      LABELS blender integration interactive
      TIMEOUT 120
      SEED 0
      FIXTURES_REQUIRED flexible_drawing_test_environment)

    # The real Realtime Plane, installed and bundled as a person gets it, launched from Blender.
    if(BLENDER_PLUGIN_WHEEL_DIR AND TARGET flexible_drawing_realtime_plane)
      flexible_drawing_add_test(
        NAME flexible_drawing.blender_realtime_plane_launch
        COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/test_blender_realtime_plane.py"
          --blender "${BLENDER_PLUGIN_EXECUTABLE}"
          --package-script "${PROJECT_SOURCE_DIR}/tools/blender/package.py"
          --extension-dir "${CMAKE_CURRENT_SOURCE_DIR}/../extension"
          --library $<TARGET_FILE:flexible_drawing_host_abi>
          --wheel-dir "${BLENDER_PLUGIN_WHEEL_DIR}"
          --interactive
          --build-dir "${CMAKE_BINARY_DIR}"
        LABELS blender integration interactive realtime_plane
        TIMEOUT 240
        SEED 0
        FIXTURES_REQUIRED flexible_drawing_test_environment)
    endif()
  endif()
endif()
