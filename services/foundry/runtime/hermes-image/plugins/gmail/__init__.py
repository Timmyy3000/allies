from tools.allies_gmail import SCHEMA, handle_gmail


def register(ctx):
    ctx.register_tool(
        name="allies_gmail",
        toolset="allies-gmail",
        schema=SCHEMA["function"],
        handler=handle_gmail,
        description=SCHEMA["function"]["description"],
    )
