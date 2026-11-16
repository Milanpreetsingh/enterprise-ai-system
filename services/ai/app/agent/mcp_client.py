import contextvars
import os
import requests
from pydantic import create_model, Field
from langchain_core.tools import StructuredTool
from app.agent.constants import DEFAULT_MCP_URL

# ContextVar storing the active authenticated user ID for the request turn
current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_user_id", default="anonymous")

def fetch_mcp_tools(mcp_url: str = None) -> list[StructuredTool]:
    """
    Connects to the API Gateway MCP Server, fetches available capabilities 
    dynamically, and translates them into LangChain StructuredTool objects.
    """
    if not mcp_url:
        mcp_url = DEFAULT_MCP_URL
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/list",
        "id": 1
    }
    
    try:
        response = requests.post(mcp_url, json=payload, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if "error" in data:
            print(f"[MCP Client] Server returned error schema: {data['error']}")
            return []
            
        tools_data = data.get("result", {}).get("tools", [])
        langchain_tools = []
        
        for tool in tools_data:
            name = tool["name"]
            description = tool["description"]
            schema = tool.get("inputSchema", {})
            properties = schema.get("properties", {})
            
            # Construct Pydantic model properties dynamically from JSON Schema
            fields = {}
            for prop_name, prop_val in properties.items():
                val_type = prop_val.get("type", "string")
                py_type = str
                if val_type == "integer":
                    py_type = int
                elif val_type == "number":
                    py_type = float
                elif val_type == "boolean":
                    py_type = bool
                    
                fields[prop_name] = (py_type, Field(default=None if prop_name not in schema.get("required", []) else ..., description=prop_val.get("description", "")))
                
            args_schema = create_model(f"{name}_input", **fields)
            
            # Define tool execution closure bound to this tool name and schema
            def make_call_func(t_name=name, tool_props=properties):
                def call_func(**kwargs):
                    # Auto-inject authenticated user_id if tool verifies ownership
                    auth_uid = current_user_id.get()
                    if "user_id" in tool_props and auth_uid and auth_uid != "anonymous":
                        kwargs["user_id"] = auth_uid

                    if t_name == "get_user_profile" and "id" in tool_props and auth_uid and auth_uid != "anonymous":
                        passed_id = str(kwargs.get("id", "")).strip()
                        if not passed_id or passed_id.lower() in ("user123", "user12345", "user-id-12345", "string", "anonymous", "current_user", "null", "none"):
                            kwargs["id"] = auth_uid

                    call_payload = {
                        "jsonrpc": "2.0",
                        "method": "tools/call",
                        "params": {
                            "name": t_name,
                            "arguments": kwargs
                        },
                        "id": 2
                    }
                    try:
                        res = requests.post(mcp_url, json=call_payload, timeout=5)
                        res.raise_for_status()
                        res_data = res.json()
                        if "error" in res_data:
                            return f"Error executing tool: {res_data['error']}"
                        content = res_data.get("result", {}).get("content", [])
                        if content:
                            return content[0].get("text", "")
                        return "Success"
                    except Exception as call_err:
                        return f"Tool execution failed: {call_err}"
                return call_func

                
            structured_tool = StructuredTool(
                name=name,
                description=description,
                func=make_call_func(name),
                args_schema=args_schema
            )
            langchain_tools.append(structured_tool)
            print(f"[MCP Client] Dynamically imported tool: {name}")
            
        return langchain_tools
    except Exception as e:
        print(f"[MCP Client] Warning: failed to fetch MCP tools from {mcp_url}: {e}. Operating without dynamic tools.")
        return []
