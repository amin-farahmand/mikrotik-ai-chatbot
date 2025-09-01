import streamlit as st
import routeros_api
import time
import google.generativeai as genai
import json
import re

# --- Gemini AI Integration ---
def get_ai_response(user_input, api_key):
    """
    Uses the Gemini API to analyze user input and determine the intended
    MikroTik command.

    Args:
        user_input (str): The natural language command from the user.
        api_key (str): The Google AI API key.

    Returns:
        dict: A dictionary containing the command path and parameters, or None.
    """
    if not api_key:
        st.error("Google AI API Key is not set. Please add it in the sidebar.")
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except Exception as e:
        st.error(f"Failed to configure AI model. Is your API key correct? Error: {e}")
        return None


    # This is the crucial part: We tell the AI how it should behave and what its goal is.
    system_prompt = """
    You are a highly intelligent assistant for MikroTik RouterOS. Your only task is to translate a user's plain English request into a single, valid JSON object representing the corresponding RouterOS API resource path.

    The JSON object MUST contain two keys:
    1. "cmd": The API resource path as a string (e.g., "/system/resource"). DO NOT include "/print".
    2. "params": A dictionary of parameters. This can be an empty dictionary {} if no parameters are needed.

    YOU MUST ONLY OUTPUT THE RAW JSON OBJECT AND NOTHING ELSE. Do not include explanations, apologies, or any markdown formatting like ```json.

    Here are some examples of API resource paths for your reference:
    - /system/resource
    - /log
    - /interface
    - /ip/address
    - /ip/firewall/filter
    - /interface/wireless/registration-table
    - /ip/dhcp-server/lease
    - /system/reboot

    Example 1:
    User request: "what is the router uptime?"
    Your response:
    {"cmd": "/system/resource", "params": {}}

    Example 2:
    User request: "show connected wifi devices"
    Your response:
    {"cmd": "/interface/wireless/registration-table", "params": {}}
    
    Example 3:
    User request: "how many clients are online?"
    Your response:
    {"cmd": "/ip/dhcp-server/lease", "params": {}}

    Now, process the following user request.
    """
    
    try:
        full_prompt = f"{system_prompt}\nUser request: \"{user_input}\""
        response = model.generate_content(full_prompt)
        
        # Use regex to find the JSON block, making parsing more robust
        json_match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if not json_match:
            st.error("AI Response Error: The model did not return a valid command object.")
            print(f"AI Raw Response: {response.text}") # For server-side debugging
            return None

        command_str = json_match.group(0)
        command_info = json.loads(command_str)
        
        if "cmd" in command_info and isinstance(command_info.get("params"), dict):
            return command_info
        else:
            st.error("AI Response Error: The returned command is missing required keys.")
            return None
            
    except json.JSONDecodeError:
        st.error("AI Response Error: Failed to parse the command from the model's response.")
        print(f"AI Raw Response (failed to parse): {response.text}")
        return None
    except Exception as e:
        # Provide more specific feedback for common errors like invalid API key
        if "API_KEY_INVALID" in str(e):
             st.error("Authentication Error: Your Google AI API Key is invalid. Please check it in the sidebar.")
        else:
            st.error(f"An unexpected AI error occurred. Please check the console for details.")
        print(f"Error during AI processing: {e}") # Keep server-side logging
        return None


# --- Core Chatbot Functions (mostly unchanged) ---

def connect_to_mikrotik(host, user, password):
    """Establishes a connection to the MikroTik router."""
    try:
        connection = routeros_api.RouterOsApiPool(host, username=user, password=password, plaintext_login=True)
        api = connection.get_api()
        st.session_state['api_connection'] = api
        st.session_state['connection_pool'] = connection
        return True
    except routeros_api.exceptions.RouterOsApiConnectionError as e:
        st.sidebar.error(f"Connection Error: {e}")
        return False
    except Exception as e:
        st.sidebar.error(f"An unexpected error occurred: {e}")
        return False

def execute_command(api, command_info):
    """Executes a command on the MikroTik router and returns the result."""
    if not command_info:
        return "The AI could not determine a valid command for your request. Please try rephrasing it."

    cmd_path = command_info['cmd']
    params = command_info.get('params', {})
    
    try:
        if cmd_path == '/system/reboot':
            return "Reboot command received. Please use the 'System Controls' section in the sidebar to confirm the reboot."

        result = api.get_resource(cmd_path).get(**params)
        return result
    except Exception as e:
        return f"An error occurred while executing the command: {e}"

def format_response(response, command_info):
    """Formats the API response for better readability and adds contextual info."""
    if isinstance(response, str):
        return response
    if not response:
        return "No results found or command executed successfully."

    count_string = ""
    # Check if the command was to get DHCP leases to provide a count
    if command_info and command_info.get('cmd') == '/ip/dhcp-server/lease':
        # Filter for leases that are actually active ('bound')
        active_leases = [lease for lease in response if lease.get('status') == 'bound']
        count = len(active_leases)
        count_string = f"### 💡 Found {count} active client(s) online.\n\n---\n\n"


    formatted_string = ""
    for item in response:
        lines = [f"- **{k.replace('-', ' ').title()}**: `{v}`" for k, v in item.items()]
        formatted_string += "\n".join(lines) + "\n\n---\n\n"
    return count_string + formatted_string

# --- Streamlit App UI ---

st.set_page_config(page_title="MikroTik AI Chatbot", layout="wide")
st.title("🤖 MikroTik AI Chatbot (Gemini Powered)")
st.caption("A conversational interface for managing your MikroTik router.")

if 'api_connection' not in st.session_state:
    st.session_state['api_connection'] = None
if 'connection_pool' not in st.session_state:
    st.session_state['connection_pool'] = None
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": "Hello! Please provide your credentials and API key in the sidebar to get started."}]

with st.sidebar:
    st.header("Router Connection")
    host = st.text_input("Router IP/Host", key="host")
    user = st.text_input("Username", value="admin", key="user")
    password = st.text_input("Password", type="password", key="password")
    
    st.header("AI Configuration")
    api_key = st.text_input("Google AI API Key", type="password", key="api_key", help="Get your key from Google AI Studio.")

    if st.session_state['api_connection']:
        st.success(f"Connected to {host}")
        if st.button("Disconnect"):
            st.session_state.connection_pool.disconnect()
            st.session_state['api_connection'] = None
            st.session_state['connection_pool'] = None
            st.rerun()
    else:
        if st.button("Connect"):
            if host and user and api_key:
                with st.spinner(f"Connecting to {host}..."):
                    connect_to_mikrotik(host, user, password)
                st.rerun()
            else:
                st.warning("Please provide all connection and API key details.")

    if st.session_state['api_connection']:
        st.header("System Controls")
        with st.expander("⚠️ DANGER ZONE ⚠️"):
            st.warning("These actions can disrupt your network.")
            if st.button("REBOOT ROUTER NOW"):
                try:
                    reboot_resource = st.session_state.api_connection.get_binary_resource('/system/reboot')
                    reboot_resource.call()
                    st.success("Reboot command sent successfully!")
                    time.sleep(5) 
                    st.session_state.connection_pool.disconnect()
                    st.session_state['api_connection'] = None
                    st.session_state['connection_pool'] = None
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to send reboot command: {e}")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Ask something about your router..."):
    if not st.session_state['api_connection']:
        st.info("Please connect to a router and provide an API key first.")
        st.stop()
    if not st.session_state.api_key:
        st.info("Please enter your Google AI API Key in the sidebar.")
        st.stop()


    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        with st.spinner("AI is thinking..."):
            command_info = get_ai_response(prompt, st.session_state.api_key)
            response = execute_command(st.session_state['api_connection'], command_info)
            formatted_output = format_response(response, command_info)
            message_placeholder.markdown(formatted_output)
    
    st.session_state.messages.append({"role": "assistant", "content": formatted_output})

