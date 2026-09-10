from tools.allies_routines import SCHEMA, handle_routine


def register(ctx):
    ctx.register_tool(
        name="allies_routines",
        toolset="allies-routines",
        schema=SCHEMA,
        handler=handle_routine,
        description=SCHEMA["function"]["description"],
    )
