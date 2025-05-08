# LANchat: Peer-to-Peer LAN Messenger
An AIM-inspired chat program.

PyAIM-LAN is a Python-based peer-to-peer (P2P) chat application designed for use on a Local Area Network (LAN). It features a graphical user interface (GUI) inspired by the classic AOL Instant Messenger, allowing users to discover each other on the network, engage in private one-on-one chats, and see online statuses.

The entire application is contained within a single Python file (`lanchat.py`) and uses only standard Python libraries, ensuring maximum portability and ease of use.

## Features

*   **Peer-to-Peer Communication:** No central server required after initial peer discovery. Communication is direct between clients.
*   **LAN-Only:** Operates exclusively within your local network. No internet connection or external servers are used.
*   **AOL-Inspired GUI:**
    *   Contact list displaying online users with status indicators (Online/Away/Offline).
    *   Private chat windows for one-on-one conversations.
    *   Timestamps for messages.
*   **Usernames & Status:**
    *   Set a display name upon startup.
    *   Set your status (Online, Away).
    *   Set a custom status message (e.g., "Busy", "Be right back").
*   **Automatic Peer Discovery:**
    *   Uses UDP broadcasts to find other instances of the application on the LAN.
    *   If no peers are found, the client becomes an initial connection point for others.
*   **Dynamic Network:** Handles peers joining and leaving gracefully.
*   **Resilience:** If the initial "server node" (first peer) goes offline, the network aims to remain connected through other peers (though full mesh routing is not implemented; it relies on peers knowing about each other).
*   **Message Notifications:** Basic window flashing for new messages in inactive chat windows.
*   **Chat History:** Basic persistence of chat conversations to local files (in a `lan_chat_history` sub-directory).
*   **Single File & Standard Libraries:** Easy to run and portable, requiring only a Python 3.8+ installation.

## Requirements

*   Python 3.8 or newer.
*   Standard Python libraries (socket, threading, tkinter, queue, json, time, datetime, sys, os). No external packages need to be installed.

## How to Run

1.  Ensure you have Python 3.8+ installed.
2.  Download the `lanchat.py` file (or the file containing the code).
3.  Open a terminal or command prompt.
4.  Navigate to the directory where you saved the file.
5.  Run the application using:
    ```bash
    python lanchat.py
    ```
6.  You will be prompted to enter a display name.
7.  The application will then attempt to discover other users on your LAN.

**Note on Firewalls:**
Your operating system's firewall might block the application's network communication (UDP for discovery, TCP for chat). You may need to allow Python or the specific script to communicate on the network if you encounter issues with discovery or connection.

## How It Works (Brief Overview)

1.  **Startup & Discovery:**
    *   On launch, the user provides a display name.
    *   The application broadcasts a UDP message on a predefined port (25000) to discover other running instances.
    *   Other instances respond with their own details (username, IP, TCP port).
    *   If no responses are received within a timeout, the client assumes it's the first one and starts a TCP server to listen for incoming connections.
2.  **Connection:**
    *   If peers are discovered, the client attempts to connect to one of them via TCP.
    *   Once connected, it exchanges a "HELLO" message and can receive a list of other known peers. It then tries to connect to those peers as well.
    *   New peers connecting to an existing network announce their presence, and this information is relayed to all other connected peers.
3.  **Communication:**
    *   All chat messages and status updates are sent directly between peers over TCP connections.
    *   Each client maintains its own list of connected peers and their statuses.
4.  **GUI:**
    *   Tkinter is used to create the main window (contact list) and individual chat windows.
    *   A message queue is used to safely update the GUI from network threads.
5.  **Peer Management:**
    *   Heartbeat messages (PING/PONG) are used to detect unresponsive peers.
    *   Disconnections are handled, and contact lists are updated across the network.

## Limitations

*   **Basic Text Only:** No support for file transfers, images, or rich text formatting.
*   **LAN Scope:** Strictly limited to the local network.
*   **Scalability:** Performance might degrade with a very large number of peers on the same network due to the P2P connection model.
*   **No Encryption:** Messages are sent in plain text. Not suitable for sensitive information on untrusted networks.
*   **"Server Node" Resilience:** While the system attempts to be resilient if the initial node drops, the peer discovery and initial connection logic is relatively simple. A more robust mesh network would require more complex routing and state management.

## Contributing

This project was developed as a single-file solution based on a specific prompt. While contributions are welcome, the primary constraint of keeping it within a single file using only standard libraries should be respected for any core changes.

---

Enjoy chatting on your LAN!
