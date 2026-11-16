/**
 * {file}
 * {brief} Verifies the Blender host profile changes only Blender-owned UI behavior.
 */

#include <array>
#include <cassert>
#include <ranges>

import flexible_drawing.presentation.ui_schema;
import flexible_drawing.tests.blender_ui_schema_fixture;
import flexible_drawing.tests.ui_schema_fixtures.authoring_workspace_ui;

namespace
{
    namespace schema  = flexible_drawing::presentation::ui_schema;
    namespace builder = flexible_drawing::presentation::ui_schema_builder;

    [[nodiscard]] schema::UiSchema ResolveBlenderUi()
    {
        const std::array authoringDefaults{flexible_drawing::tests::ui_schema_fixtures::AuthoringWorkspace()};
        const auto       profile{flexible_drawing::tests::blender_ui_schema::Profile()};
        const auto       resolved{builder::Resolve(authoringDefaults, &profile)};
        assert(resolved.has_value());
        return *resolved;
    }
} // namespace

int main()
{
    const auto schema{ResolveBlenderUi()};
    assert(std::ranges::find_if(schema.Sections, [](const auto &section)
                                { return section.Id.Value == "blender.tool_settings.section"; }) !=
           schema.Sections.end());
    assert(std::ranges::find(schema.Groups, schema::GroupDescriptor{.Id = {.Value = "authoring.tool.group"}}) ==
           schema.Groups.end());
    assert(std::ranges::find(schema.Relationships,
                             schema::UiRelationship{.Parent = {.Value = "blender.tool_settings.section"},
                                                    .Child  = {.Value = "authoring.tool.selector"}}) !=
           schema.Relationships.end());
}
