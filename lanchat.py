import tkinter as tk
from tkinter import simpledialog, scrolledtext, Listbox, Menu, messagebox
import socket
import threading
import json
import time
import queue
import datetime
import sys
import os

# --- Constants ---
DISCOVERY_PORT = 25000
TCP_BASE_PORT = 25001 # We'll try to find a free port starting from here
DISCOVERY_MESSAGE_REQUEST = "AIM_CLONE_DISCOVER_REQUEST_V3"
DISCOVERY_MESSAGE_RESPONSE = "AIM_CLONE_DISCOVER_RESPONSE_V3"
BUFFER_SIZE = 4096
DISCOVERY_TIMEOUT = 3  # seconds
HEARTBEAT_INTERVAL = 30 # seconds to send pings
HEARTBEAT_TIMEOUT = 90 # seconds to consider a peer offline if no pong

# --- Helper Functions ---
def get_local_ip():
    """Gets the local IP address of the machine."""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) # Doesn't send data, just finds preferred interface
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1" # Fallback
    finally:
        if s:
            s.close()
    return ip

def find_free_port(start_port):
    """Finds an available TCP port starting from start_port."""
    port = start_port
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind((get_local_ip(), port))
            s.close()
            return port
        except OSError:
            port += 1
        if port > 65535:
            raise IOError("No free ports available")

# --- ChatWindow Class ---
class ChatWindow(tk.Toplevel):
    def __init__(self, master, peer_username, app_instance, initial_history=None):
        super().__init__(master)
        self.peer_username = peer_username
        self.app = app_instance
        self.title(f"Chat with {peer_username}")
        self.geometry("400x500")

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.chat_history = scrolledtext.ScrolledText(self, state=tk.DISABLED, wrap=tk.WORD, height=20)
        self.chat_history.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        self.message_entry = tk.Entry(self, width=50)
        self.message_entry.pack(padx=10, pady=(0,5), side=tk.LEFT, fill=tk.X, expand=True)
        self.message_entry.bind("<Return>", self.send_message_event)

        self.send_button = tk.Button(self, text="Send", command=self.send_message_event)
        self.send_button.pack(padx=(0,10), pady=(0,5), side=tk.RIGHT)
        
        if initial_history:
            for item in initial_history:
                self.display_message(item['sender'], item['content'], item['timestamp'], item['is_self'])

        self.focus_set() # Focus on this new window
        self.message_entry.focus_set() # Focus on the message entry field

    def send_message_event(self, event=None):
        message_text = self.message_entry.get()
        if message_text.strip():
            self.app.send_chat_message(self.peer_username, message_text)
            self.display_message(self.app.username, message_text, 
                                 datetime.datetime.now().strftime('%H:%M:%S'), True)
            self.message_entry.delete(0, tk.END)

    def display_message(self, sender, message, timestamp, is_self=False):
        self.chat_history.config(state=tk.NORMAL)
        formatted_message = f"[{timestamp}] {sender}: {message}\n"
        if is_self:
            self.chat_history.insert(tk.END, formatted_message, "self_message")
        else:
            self.chat_history.insert(tk.END, formatted_message, "peer_message")
            # Basic notification: flash window if not active
            if not self.winfo_ismapped() or not self.focus_displayof():
                 self.app.flash_window_title(self, f"New message from {sender}!")

        self.chat_history.tag_config("self_message", foreground="blue")
        self.chat_history.tag_config("peer_message", foreground="green")
        self.chat_history.see(tk.END)
        self.chat_history.config(state=tk.DISABLED)

    def on_close(self):
        self.app.close_chat_window(self.peer_username)
        self.destroy()

    def peer_went_offline(self):
        self.chat_history.config(state=tk.NORMAL)
        self.chat_history.insert(tk.END, f"--- {self.peer_username} went offline ---\n", "system_message")
        self.chat_history.tag_config("system_message", foreground="red", font=("TkDefaultFont", 8, "italic"))
        self.chat_history.config(state=tk.DISABLED)
        self.message_entry.config(state=tk.DISABLED)
        self.send_button.config(state=tk.DISABLED)
        self.title(f"Chat with {self.peer_username} (Offline)")


# --- Main Application Class ---
class LANMessengerApp:
    def __init__(self, root):
        self.root = root
        self.username = None
        self.local_ip = get_local_ip()
        self.tcp_port = find_free_port(TCP_BASE_PORT)
        
        self.peers = {}  # {username: {'ip': str, 'port': int, 'socket': socket, 'status': str, 'last_seen': float, 'custom_status': str}}
        self.chat_windows = {} # {username: ChatWindow_instance}
        self.message_queue = queue.Queue() # For GUI updates from threads
        self.running = True
        self.status = "Online"
        self.custom_status_message = ""

        self.history_dir = "lan_chat_history"
        if not os.path.exists(self.history_dir):
            try:
                os.makedirs(self.history_dir)
            except OSError as e:
                print(f"Error creating history directory: {e}")
                self.history_dir = None # Disable history if dir creation fails

        self._prompt_username()
        if not self.username:
            root.destroy()
            sys.exit("Username not provided. Exiting.")

        self.root.title(f"LAN Messenger - {self.username} ({self.status})")
        self.root.geometry("300x500")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self._setup_gui()
        
        # Start networking components
        threading.Thread(target=self._listen_for_discovery_pings_udp, daemon=True).start()
        threading.Thread(target=self._start_tcp_server, daemon=True).start()
        threading.Thread(target=self._broadcast_discovery_udp_and_listen, daemon=True).start()
        threading.Thread(target=self._heartbeat_peers, daemon=True).start()

        self.root.after(100, self._process_message_queue)

    def _prompt_username(self):
        self.username = simpledialog.askstring("Username", "Enter your display name:", parent=self.root)
        if not self.username: # User cancelled or entered nothing
            self.username = f"User_{int(time.time())%1000}" # Default if cancelled
            # messagebox.showerror("Error", "Username cannot be empty.")
            # self.root.destroy()
            # sys.exit()
        self.username = self.username.replace(" ", "_").strip() # Sanitize

    def _setup_gui(self):
        # Menu
        menubar = Menu(self.root)
        status_menu = Menu(menubar, tearoff=0)
        status_menu.add_command(label="Online", command=lambda: self.set_status("Online"))
        status_menu.add_command(label="Away", command=lambda: self.set_status("Away"))
        status_menu.add_command(label="Set Custom Status", command=self.set_custom_status_dialog)
        status_menu.add_separator()
        status_menu.add_command(label="Exit", command=self.on_closing)
        menubar.add_cascade(label="Status", menu=status_menu)
        self.root.config(menu=menubar)

        # Self status label
        self.self_status_label = tk.Label(self.root, text=f"You are: {self.status}")
        self.self_status_label.pack(pady=5)

        # Contact List
        tk.Label(self.root, text="Online Users:").pack()
        self.contact_list_frame = tk.Frame(self.root)
        self.contact_list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.contact_list_scrollbar = tk.Scrollbar(self.contact_list_frame, orient=tk.VERTICAL)
        self.contact_list = Listbox(self.contact_list_frame, yscrollcommand=self.contact_list_scrollbar.set)
        self.contact_list_scrollbar.config(command=self.contact_list.yview)
        self.contact_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.contact_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.contact_list.bind("<Double-Button-1>", self._on_contact_double_click)

    def _update_gui_contact_list(self):
        self.contact_list.delete(0, tk.END)
        sorted_peers = sorted(self.peers.items(), key=lambda item: item[0].lower()) # Sort by username
        for username, data in sorted_peers:
            status_icon = "🟢" if data.get('status') == "Online" else ("🟡" if data.get('status') == "Away" else "⚪️")
            display_text = f"{status_icon} {username}"
            if data.get('custom_status'):
                display_text += f" - {data['custom_status']}"
            self.contact_list.insert(tk.END, display_text)
        
        # Update title with current status
        title_status = self.status
        if self.custom_status_message:
            title_status += f" - {self.custom_status_message}"
        self.root.title(f"LAN Messenger - {self.username} ({title_status})")
        self.self_status_label.config(text=f"You are: {title_status}")


    def _on_contact_double_click(self, event):
        selection = self.contact_list.curselection()
        if selection:
            selected_text = self.contact_list.get(selection[0])
            # Extract username (it's between the icon and possible custom status)
            peer_username = selected_text.split(" ", 2)[1] # "🟢 User - Custom" -> "User"
            if peer_username != self.username and peer_username in self.peers:
                self._open_chat_window(peer_username)

    def _open_chat_window(self, peer_username):
        if peer_username in self.chat_windows and self.chat_windows[peer_username].winfo_exists():
            self.chat_windows[peer_username].lift()
            self.chat_windows[peer_username].focus_set()
        else:
            initial_history = self._load_chat_history(peer_username)
            chat_win = ChatWindow(self.root, peer_username, self, initial_history)
            self.chat_windows[peer_username] = chat_win
            if self.peers.get(peer_username, {}).get('status') == "Offline":
                chat_win.peer_went_offline()


    def close_chat_window(self, peer_username):
        if peer_username in self.chat_windows:
            # Save history before removing from dict
            self._save_chat_history(peer_username, self.chat_windows[peer_username])
            del self.chat_windows[peer_username]

    def set_status(self, new_status, custom_message=""):
        self.status = new_status
        self.custom_status_message = custom_message if new_status != "Offline" else "" # Offline clears custom message
        self._update_gui_contact_list() # Update self status display
        self._broadcast_message({
            "type": "STATUS_UPDATE",
            "username": self.username,
            "status": self.status,
            "custom_status": self.custom_status_message,
            "timestamp": time.time()
        })

    def set_custom_status_dialog(self):
        custom_msg = simpledialog.askstring("Custom Status", "Enter your custom status message:",
                                            initialvalue=self.custom_status_message, parent=self.root)
        if custom_msg is not None: # User pressed OK (could be empty string)
            self.set_status(self.status, custom_msg) # Keep current online/away status

    def flash_window_title(self, window, message, count=5, interval=500):
        original_title = window.title()
        def flash(c):
            if not window.winfo_exists(): return # Window closed
            if c % 2 == 0:
                window.title(message)
            else:
                window.title(original_title)
            if c > 0:
                window.after(interval, flash, c - 1)
            else: # Ensure original title is restored
                 if window.winfo_exists(): window.title(original_title)
        
        # Only flash if window is not focused
        is_focused = False
        try:
            is_focused = (window.focus_displayof() == window)
        except tk.TclError: # Can happen if window is being destroyed
            pass

        if not is_focused:
            flash(count * 2 -1) # Flash on/off for 'count' times

    # --- Networking Methods ---
    def _listen_for_discovery_pings_udp(self):
        """Listens for discovery broadcasts from other peers."""
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            udp_sock.bind(("", DISCOVERY_PORT)) # Listen on all interfaces
        except OSError as e:
            print(f"Error binding UDP discovery listener: {e}. Discovery response might not work.")
            udp_sock.close()
            return

        print(f"Listening for discovery pings on UDP port {DISCOVERY_PORT}")
        while self.running:
            try:
                data, addr = udp_sock.recvfrom(BUFFER_SIZE)
                message = data.decode('utf-8')
                if message.startswith(DISCOVERY_MESSAGE_REQUEST):
                    parts = message.split(":")
                    if len(parts) == 4: # DISCOVER_MSG:SENDER_USER:SENDER_TCP_PORT:SENDER_IP
                        req_username = parts[1]
                        req_tcp_port = int(parts[2])
                        req_ip = parts[3] # The IP address the sender claims to have for TCP

                        if req_username == self.username: continue # Don't respond to self

                        print(f"Received discovery ping from {req_username} at {req_ip}:{req_tcp_port}")
                        response = f"{DISCOVERY_MESSAGE_RESPONSE}:{self.username}:{self.tcp_port}:{self.local_ip}"
                        # Send response directly to the sender's address from the packet
                        udp_sock.sendto(response.encode('utf-8'), addr) 
            except Exception as e:
                if self.running: # Avoid error message if we are shutting down
                    print(f"Error in UDP discovery listener: {e}")
                time.sleep(1) # Avoid busy-looping on error
        udp_sock.close()

    def _broadcast_discovery_udp_and_listen(self):
        """Broadcasts our presence and listens for responses for a short time."""
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_sock.settimeout(0.1) # Short timeout for recvfrom

        message = f"{DISCOVERY_MESSAGE_REQUEST}:{self.username}:{self.tcp_port}:{self.local_ip}"
        
        # Try to broadcast on common broadcast addresses
        broadcast_addresses = ['<broadcast>', '255.255.255.255']
        # Add specific interface broadcast if possible (more complex to get reliably cross-platform)

        for b_addr in broadcast_addresses:
            try:
                udp_sock.sendto(message.encode('utf-8'), (b_addr, DISCOVERY_PORT))
            except Exception as e:
                print(f"Could not broadcast to {b_addr}: {e}")
        print(f"Broadcasted discovery message: {message}")

        responded_peers = set()
        start_time = time.time()
        while time.time() - start_time < DISCOVERY_TIMEOUT:
            try:
                data, addr = udp_sock.recvfrom(BUFFER_SIZE)
                response_str = data.decode('utf-8')
                if response_str.startswith(DISCOVERY_MESSAGE_RESPONSE):
                    parts = response_str.split(":")
                    if len(parts) == 4: # RESPONSE_MSG:PEER_USER:PEER_TCP_PORT:PEER_IP
                        peer_username = parts[1]
                        peer_tcp_port = int(parts[2])
                        peer_ip = parts[3] # The IP the peer claims for TCP

                        if peer_username != self.username and peer_username not in self.peers:
                            if peer_username not in responded_peers:
                                print(f"Discovered peer {peer_username} at {peer_ip}:{peer_tcp_port}")
                                self.message_queue.put(("initiate_connection", {
                                    "username": peer_username, "ip": peer_ip, "port": peer_tcp_port
                                }))
                                responded_peers.add(peer_username)
            except socket.timeout:
                pass # Expected
            except Exception as e:
                print(f"Error receiving discovery response: {e}")
            time.sleep(0.1) # Brief pause
        udp_sock.close()
        if not responded_peers:
            print("No peers found during initial discovery.")


    def _start_tcp_server(self):
        """Starts the TCP server to listen for incoming peer connections."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.local_ip, self.tcp_port))
            self.server_socket.listen(5)
            print(f"TCP server listening on {self.local_ip}:{self.tcp_port}")
        except Exception as e:
            print(f"!!! Critical: Could not start TCP server: {e}. Application may not function correctly.")
            self.message_queue.put(("show_error", f"Could not bind to {self.local_ip}:{self.tcp_port}. Try restarting or check firewall."))
            self.running = False # Stop other threads
            return

        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                print(f"Accepted connection from {addr}")
                # The first message from a new connection should be HELLO
                # Handle this in a new thread to not block the accept loop
                threading.Thread(target=self._handle_incoming_peer, args=(conn, addr), daemon=True).start()
            except OSError: # Socket closed, likely during shutdown
                if self.running: print("TCP server socket error.")
                break 
            except Exception as e:
                if self.running:
                    print(f"Error in TCP server accept loop: {e}")
                break
        if self.server_socket:
            self.server_socket.close()
        print("TCP server stopped.")

    def _handle_incoming_peer(self, conn_socket, addr):
        """Handles a new incoming TCP connection after it's accepted."""
        peer_ip = addr[0]
        peer_username = None
        try:
            # Use makefile for easier line-by-line reading
            fileobj_r = conn_socket.makefile('r', encoding='utf-8', newline='\n')
            
            # First message should be HELLO
            hello_line = fileobj_r.readline()
            if not hello_line:
                print(f"No HELLO from {addr}, closing connection.")
                conn_socket.close()
                return

            message_data = json.loads(hello_line.strip())
            
            if message_data.get("type") == "HELLO":
                peer_username = message_data["username"]
                peer_tcp_port = message_data["port"] # Their listening port
                peer_status = message_data.get("status", "Online")
                peer_custom_status = message_data.get("custom_status", "")

                if peer_username == self.username: # Connecting to self?
                    print(f"Connection from self ({peer_username}), ignoring.")
                    conn_socket.close()
                    return

                print(f"Received HELLO from {peer_username} ({peer_ip}:{peer_tcp_port})")

                # Add or update peer
                # The socket here is the one we use to *talk back* to this peer
                # who initiated the connection to us.
                self.peers[peer_username] = {
                    "ip": peer_ip, # Their IP as seen by us
                    "port": peer_tcp_port, # Their *listening* port, not conn_socket's remote port
                    "socket": conn_socket, 
                    "status": peer_status,
                    "custom_status": peer_custom_status,
                    "last_seen": time.time(),
                    "fileobj_r": fileobj_r, # Store for reading
                    "fileobj_w": conn_socket.makefile('w', encoding='utf-8', newline='\n') # Store for writing
                }
                self.message_queue.put(("update_contacts", None))

                # Send PEER_LIST to the new peer
                self._send_message_to_peer_socket(conn_socket, {
                    "type": "PEER_LIST",
                    "peers": self._get_serializable_peers_info()
                })

                # Broadcast new peer to others
                self._broadcast_message({
                    "type": "NEW_PEER",
                    "username": peer_username,
                    "ip": peer_ip, # Their IP
                    "port": peer_tcp_port, # Their listening TCP port
                    "status": peer_status,
                    "custom_status": peer_custom_status
                }, exclude_username=peer_username)
                
                # Now, continuously listen to this peer
                self._listen_to_peer_messages(peer_username, conn_socket, fileobj_r)

            else:
                print(f"Unexpected first message from {addr}: {message_data.get('type')}, closing.")
                conn_socket.close()

        except (json.JSONDecodeError, KeyError, ConnectionResetError, BrokenPipeError) as e:
            print(f"Error handling incoming peer {peer_username or addr}: {e}")
            if peer_username and peer_username in self.peers:
                self.message_queue.put(("peer_disconnected", peer_username))
        except Exception as e:
            print(f"Unhandled error with incoming peer {peer_username or addr}: {e}")
            if peer_username and peer_username in self.peers:
                self.message_queue.put(("peer_disconnected", peer_username))
        finally:
            # If _listen_to_peer_messages wasn't started or exited early, ensure socket is closed
            if peer_username and peer_username in self.peers and self.peers[peer_username].get('socket') == conn_socket:
                 pass # _listen_to_peer_messages will handle cleanup
            else:
                try:
                    conn_socket.close()
                except: pass


    def _initiate_tcp_connection(self, peer_info):
        """Initiates a TCP connection to a discovered peer."""
        peer_username = peer_info["username"]
        peer_ip = peer_info["ip"]
        peer_port = peer_info["port"]

        if peer_username == self.username or peer_username in self.peers:
            # print(f"Already connected or attempting to connect to {peer_username}, or it's self.")
            return

        print(f"Attempting to connect to {peer_username} at {peer_ip}:{peer_port}")
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_socket.settimeout(5) # Connection timeout
            client_socket.connect((peer_ip, peer_port))
            client_socket.settimeout(None) # Reset timeout for blocking operations

            fileobj_r = client_socket.makefile('r', encoding='utf-8', newline='\n')
            fileobj_w = client_socket.makefile('w', encoding='utf-8', newline='\n')

            # Send HELLO message
            hello_message = {
                "type": "HELLO",
                "username": self.username,
                "port": self.tcp_port, # My listening port
                "status": self.status,
                "custom_status": self.custom_status_message
            }
            fileobj_w.write(json.dumps(hello_message) + '\n')
            fileobj_w.flush()
            
            print(f"Sent HELLO to {peer_username}")

            # Temporarily add peer, will be confirmed/updated by PEER_LIST or other messages
            self.peers[peer_username] = {
                "ip": peer_ip, 
                "port": peer_port, # Their listening port
                "socket": client_socket, 
                "status": "Connecting", # Will be updated
                "custom_status": "",
                "last_seen": time.time(),
                "fileobj_r": fileobj_r,
                "fileobj_w": fileobj_w
            }
            self.message_queue.put(("update_contacts", None))
            
            # Start listening to this peer in a new thread
            threading.Thread(target=self._listen_to_peer_messages, args=(peer_username, client_socket, fileobj_r), daemon=True).start()

        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            print(f"Failed to connect to {peer_username} ({peer_ip}:{peer_port}): {e}")
            if peer_username in self.peers: # Clean up if partially added
                del self.peers[peer_username]
            self.message_queue.put(("update_contacts", None))
        except Exception as e:
            print(f"Unexpected error connecting to {peer_username}: {e}")
            if peer_username in self.peers:
                del self.peers[peer_username]
            self.message_queue.put(("update_contacts", None))


    def _listen_to_peer_messages(self, peer_username, peer_socket, fileobj_r):
        """Listens for messages from an established peer connection."""
        try:
            for line in fileobj_r: # Reads until newline
                if not self.running: break
                if not line.strip(): continue # Skip empty lines if any

                message_data = json.loads(line.strip())
                message_type = message_data.get("type")
                
                # Always update last_seen on any valid message
                if peer_username in self.peers:
                    self.peers[peer_username]["last_seen"] = time.time()

                if message_type == "CHAT_MESSAGE":
                    self.message_queue.put(("chat_message", message_data))
                elif message_type == "PEER_LIST":
                    self.message_queue.put(("peer_list_received", message_data["peers"]))
                elif message_type == "NEW_PEER":
                    # A peer is telling us about another new peer
                    self.message_queue.put(("new_peer_announced", message_data))
                elif message_type == "STATUS_UPDATE":
                    self.message_queue.put(("status_update_received", message_data))
                elif message_type == "PEER_OFFLINE": # Explicit disconnect from another peer
                    if message_data["username"] != self.username: # Not about self
                         self.message_queue.put(("peer_disconnected", message_data["username"]))
                elif message_type == "PING":
                    pong_message = {"type": "PONG", "username": self.username, "timestamp": time.time()}
                    self._send_message_to_peer_socket(peer_socket, pong_message)
                elif message_type == "PONG":
                    # Handled by last_seen update already
                    pass 
                else:
                    print(f"Unknown message type from {peer_username}: {message_type}")
            
            # If loop finishes, it means fileobj_r closed (peer disconnected)
            if self.running: # Only if not shutting down
                print(f"Connection closed by {peer_username} (EOF)")
                self.message_queue.put(("peer_disconnected", peer_username))

        except (json.JSONDecodeError, ConnectionResetError, BrokenPipeError, OSError) as e:
            if self.running:
                print(f"Error listening to {peer_username}: {e}")
                self.message_queue.put(("peer_disconnected", peer_username))
        except Exception as e:
            if self.running:
                print(f"Unhandled error listening to {peer_username}: {e}")
                self.message_queue.put(("peer_disconnected", peer_username))
        finally:
            # Ensure cleanup if this thread exits for any reason
            if peer_username in self.peers and self.peers[peer_username].get('socket') == peer_socket:
                self._cleanup_peer_connection(peer_username)


    def _send_message_to_peer_socket(self, peer_socket, message_dict):
        """Sends a JSON message to a specific peer's socket."""
        if not peer_socket: return False
        try:
            # Find the peer_username associated with this socket to use its file object
            target_username = None
            for uname, p_data in self.peers.items():
                if p_data.get('socket') == peer_socket:
                    target_username = uname
                    break
            
            if target_username and self.peers[target_username].get('fileobj_w'):
                fileobj_w = self.peers[target_username]['fileobj_w']
                fileobj_w.write(json.dumps(message_dict) + '\n')
                fileobj_w.flush()
                return True
            else: # Fallback or if fileobj_w not found (should not happen in normal flow)
                peer_socket.sendall((json.dumps(message_dict) + '\n').encode('utf-8'))
                return True
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            print(f"Error sending message (socket likely closed): {e}")
            # The listening thread for this peer will handle the disconnect.
            # We can try to find the username for immediate queueing of disconnect.
            for uname, data in list(self.peers.items()): # Iterate over a copy
                if data.get('socket') == peer_socket:
                    self.message_queue.put(("peer_disconnected", uname))
                    break
            return False
        except Exception as e:
            print(f"Unexpected error sending message: {e}")
            return False

    def _broadcast_message(self, message_dict, exclude_username=None):
        """Broadcasts a message to all connected peers."""
        # Iterate over a copy of peers keys in case of modification during iteration
        for username in list(self.peers.keys()):
            if username == exclude_username:
                continue
            if username in self.peers and self.peers[username].get('socket'):
                self._send_message_to_peer_socket(self.peers[username]['socket'], message_dict)

    def send_chat_message(self, recipient_username, text_message):
        if recipient_username in self.peers and self.peers[recipient_username].get('status') != "Offline":
            message = {
                "type": "CHAT_MESSAGE",
                "sender": self.username,
                "recipient": recipient_username,
                "content": text_message,
                "timestamp": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            if self._send_message_to_peer_socket(self.peers[recipient_username]['socket'], message):
                # Save to local history as well
                self._add_to_chat_history(recipient_username, self.username, text_message, message['timestamp'], True)
        else:
            # Optionally, inform user that recipient is offline or not found
            if recipient_username in self.chat_windows:
                 self.chat_windows[recipient_username].display_message("System", f"Could not send. {recipient_username} may be offline.", datetime.datetime.now().strftime('%H:%M:%S'))


    def _get_serializable_peers_info(self):
        """Returns a list of peer info suitable for JSON serialization."""
        info_list = []
        for uname, data in self.peers.items():
            info_list.append({
                "username": uname,
                "ip": data["ip"],
                "port": data["port"], # Their listening port
                "status": data.get("status", "Unknown"),
                "custom_status": data.get("custom_status", "")
            })
        # Also include self, so others know about us
        info_list.append({
            "username": self.username,
            "ip": self.local_ip,
            "port": self.tcp_port,
            "status": self.status,
            "custom_status": self.custom_status_message
        })
        return info_list

    def _cleanup_peer_connection(self, peer_username):
        """Safely closes socket and removes peer."""
        if peer_username in self.peers:
            peer_data = self.peers.pop(peer_username) # Remove first to prevent race conditions
            sock = peer_data.get('socket')
            if sock:
                try: sock.shutdown(socket.SHUT_RDWR)
                except: pass
                try: sock.close()
                except: pass
            
            # Close file objects if they exist
            fileobj_r = peer_data.get('fileobj_r')
            if fileobj_r:
                try: fileobj_r.close()
                except: pass
            fileobj_w = peer_data.get('fileobj_w')
            if fileobj_w:
                try: fileobj_w.close()
                except: pass

            print(f"Cleaned up connection for {peer_username}")
            self.message_queue.put(("update_contacts", None)) # Ensure GUI updates
            # Update chat window if open
            if peer_username in self.chat_windows:
                self.chat_windows[peer_username].peer_went_offline()


    def _heartbeat_peers(self):
        """Periodically pings peers and checks for timeouts."""
        while self.running:
            time.sleep(HEARTBEAT_INTERVAL)
            if not self.running: break

            current_time = time.time()
            peers_to_ping = list(self.peers.keys()) # Iterate over a copy

            for username in peers_to_ping:
                if username not in self.peers: continue # Peer might have disconnected

                peer_data = self.peers[username]
                if peer_data.get('socket'):
                    # Check last_seen time
                    if current_time - peer_data.get("last_seen", 0) > HEARTBEAT_TIMEOUT:
                        print(f"Heartbeat timeout for {username}. Disconnecting.")
                        self.message_queue.put(("peer_disconnected", username))
                        continue # Move to next peer

                    # Send PING
                    ping_message = {"type": "PING", "username": self.username, "timestamp": current_time}
                    self._send_message_to_peer_socket(peer_data['socket'], ping_message)
    
    # --- Chat History Persistence ---
    def _get_history_filepath(self, peer_username):
        if not self.history_dir: return None
        # Sanitize peer_username for filename
        safe_peer_username = "".join(c if c.isalnum() else "_" for c in peer_username)
        return os.path.join(self.history_dir, f"history_{self.username}_with_{safe_peer_username}.jsonlog")

    def _load_chat_history(self, peer_username):
        filepath = self._get_history_filepath(peer_username)
        if not filepath or not os.path.exists(filepath):
            return []
        
        history = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        history_item = json.loads(line.strip())
                        history.append(history_item)
                    except json.JSONDecodeError:
                        print(f"Skipping malformed line in history for {peer_username}")
            return history
        except Exception as e:
            print(f"Error loading chat history for {peer_username}: {e}")
            return []

    def _add_to_chat_history(self, peer_username, sender, content, timestamp, is_self):
        filepath = self._get_history_filepath(peer_username)
        if not filepath: return

        history_item = {
            "sender": sender,
            "content": content,
            "timestamp": timestamp, # Already formatted string
            "is_self": is_self
        }
        try:
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(json.dumps(history_item) + '\n')
        except Exception as e:
            print(f"Error saving chat message to history for {peer_username}: {e}")

    def _save_chat_history(self, peer_username, chat_window_instance):
        # This is now handled by _add_to_chat_history incrementally.
        # This method could be used for a bulk save if needed, but not currently essential.
        pass


    # --- GUI Message Queue Processing ---
    def _process_message_queue(self):
        try:
            while not self.message_queue.empty():
                message_type, data = self.message_queue.get_nowait()

                if message_type == "update_contacts":
                    self._update_gui_contact_list()
                
                elif message_type == "chat_message":
                    sender = data["sender"]
                    content = data["content"]
                    timestamp = data["timestamp"] # This is already formatted string
                    
                    if sender not in self.chat_windows or not self.chat_windows[sender].winfo_exists():
                        self._open_chat_window(sender) # This will load history
                    
                    # The open_chat_window might have already displayed historical messages.
                    # We only display the new one here.
                    if sender in self.chat_windows:
                        self.chat_windows[sender].display_message(sender, content, timestamp.split(" ")[1] if " " in timestamp else timestamp) # Show only H:M:S for brevity
                        self._add_to_chat_history(sender, sender, content, timestamp, False) # Save received message

                elif message_type == "peer_list_received":
                    received_peers_info = data
                    for peer_info in received_peers_info:
                        p_user = peer_info["username"]
                        if p_user != self.username and p_user not in self.peers:
                            # This peer is new to us, initiate connection
                            print(f"Peer list contains new peer {p_user}, attempting to connect.")
                            self._initiate_tcp_connection(peer_info) # peer_info has ip, port
                        elif p_user in self.peers: # Update existing peer's status from list if it's more recent
                             self.peers[p_user]['status'] = peer_info.get('status', self.peers[p_user]['status'])
                             self.peers[p_user]['custom_status'] = peer_info.get('custom_status', self.peers[p_user].get('custom_status',''))
                    self._update_gui_contact_list()

                elif message_type == "new_peer_announced":
                    # Another peer told us about this new_peer_info
                    new_peer_info = data
                    p_user = new_peer_info["username"]
                    if p_user != self.username and p_user not in self.peers:
                        print(f"Received announcement for new peer {p_user}, attempting to connect.")
                        self._initiate_tcp_connection(new_peer_info) # new_peer_info has ip, port
                    elif p_user in self.peers: # Potentially update status
                        self.peers[p_user]['status'] = new_peer_info.get('status', self.peers[p_user]['status'])
                        self.peers[p_user]['custom_status'] = new_peer_info.get('custom_status', self.peers[p_user].get('custom_status',''))
                    self._update_gui_contact_list()
                
                elif message_type == "status_update_received":
                    p_user = data["username"]
                    if p_user in self.peers:
                        self.peers[p_user]["status"] = data["status"]
                        self.peers[p_user]["custom_status"] = data.get("custom_status", "")
                        self.peers[p_user]["last_seen"] = time.time() # Update last seen on status change
                        self._update_gui_contact_list()
                        if data["status"] == "Offline": # If they explicitly went offline
                            if p_user in self.chat_windows:
                                self.chat_windows[p_user].peer_went_offline()
                            # No need to call _cleanup_peer_connection here,
                            # their socket will close and heartbeat/listen thread will handle it.
                            # Or, if they sent "Offline" then DISCONNECT, that's fine too.

                elif message_type == "peer_disconnected":
                    username_dc = data # data is the username
                    if username_dc in self.peers:
                        print(f"Processing disconnect for {username_dc} from queue.")
                        self._cleanup_peer_connection(username_dc) # This updates GUI
                    # _update_gui_contact_list() is called by _cleanup_peer_connection

                elif message_type == "initiate_connection": # From initial discovery
                    self._initiate_tcp_connection(data) # data is peer_info dict

                elif message_type == "show_error":
                    messagebox.showerror("Error", data, parent=self.root)


        except queue.Empty:
            pass # No messages
        except Exception as e:
            print(f"Error processing GUI queue: {e}")
        finally:
            if self.running:
                self.root.after(100, self._process_message_queue) # Reschedule

    def on_closing(self):
        print("Closing application...")
        self.running = False # Signal all threads to stop

        # Set status to Offline and broadcast (best effort)
        self.set_status("Offline") 
        # Give a moment for the broadcast to go out.
        # A more robust way would be synchronous broadcast or waiting for ACKs.
        time.sleep(0.2) 

        # Close all peer connections
        for username in list(self.peers.keys()): # Iterate over a copy
            self._cleanup_peer_connection(username)
        
        # Close server socket
        if hasattr(self, 'server_socket') and self.server_socket:
            try:
                self.server_socket.close()
            except Exception as e:
                print(f"Error closing server socket: {e}")
        
        # Save any open chat histories
        for username, chat_win in list(self.chat_windows.items()):
            if chat_win.winfo_exists():
                 self._save_chat_history(username, chat_win) # Currently a no-op due to incremental save
                 chat_win.destroy()

        print("All connections closed. Exiting.")
        self.root.destroy()
        sys.exit(0)


if __name__ == "__main__":
    root = tk.Tk()
    app = LANMessengerApp(root)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        print("Keyboard interrupt received.")
        app.on_closing()
