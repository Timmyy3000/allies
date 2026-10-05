from tools.allies_calendar import SCHEMA, handle_calendar


def register(ctx):
    ctx.register_tool(
        name="allies_calendar",
        toolset="allies-calendar",
        schema=SCHEMA["function"],
        handler=handle_calendar,
        description=SCHEMA["function"]["description"],
    )
