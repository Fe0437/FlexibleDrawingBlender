/**
 * {file}
 * {brief} Blender host-profile fixture for the semantic UI schema tests.
 */
module;

export module flexible_drawing.tests.blender_ui_schema_fixture;

export import flexible_drawing.tests.ui_schema_fixtures.authoring_workspace_ui;

namespace flexible_drawing::tests::blender_ui_schema
{
    using namespace presentation::ui_schema_builder;
}

export namespace flexible_drawing::tests::blender_ui_schema
{
    namespace ids
    {
        /** {brief} Section that projects active tool settings into Blender UI. */
        inline constexpr Id ToolSettingsSection{"blender.tool_settings.section"};
    } // namespace ids

    /** {brief} Build the Blender-specific changes to the authoring workspace UI fixture. */
    [[nodiscard]] HostProfile Profile()
    {
        return presentation::ui_schema_builder::Profile("blender")
            .Add(Under(ui_schema_fixtures::authoring_ids::Workspace, Section(ids::ToolSettingsSection)))
            .Replace(ChoiceControl(ui_schema_fixtures::authoring_ids::ToolSelector,
                                   IdentityState{"core.tool", "active_tool"},
                                   IdentityAction{"blender.tool", "select_tool"}))
            .Move(ui_schema_fixtures::authoring_ids::ToolSelector, Into(ids::ToolSettingsSection))
            .Move(ui_schema_fixtures::authoring_ids::BrushSizeControl, Into(ids::ToolSettingsSection))
            .Omit(ui_schema_fixtures::authoring_ids::ToolGroup);
    }
} // namespace flexible_drawing::tests::blender_ui_schema
