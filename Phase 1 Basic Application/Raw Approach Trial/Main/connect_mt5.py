import MetaTrader5 as mt5

def connect_to_mt5(account_id: int, password: str, server: str) -> bool:
    """
    Connect to MetaTrader 5 using account id, password, and server.
    """
    # Initialize connection to the MetaTrader 5 terminal
    if not mt5.initialize():
        print(f"mt5.initialize() failed, error code = {mt5.last_error()}")
        return False

    # Attempt to log in to the specified account
    authorized = mt5.login(account_id, password=password, server=server)
    
    if authorized:
        print(f"Successfully connected to account #{account_id} on server '{server}'")
        return True
    else:
        print(f"Failed to connect to account #{account_id}, error code: {mt5.last_error()}")
        return False

# Example usage (Replace with actual credentials):
ACCOUNT_ID = 433400695  # Note: Account ID must be an integer
PASSWORD = "Soham@987"
SERVER = "Exness-MT5Trial7"

connect_to_mt5(ACCOUNT_ID, PASSWORD, SERVER)


if __name__ == "__main__":
    print(mt5.terminal_info())
    print(mt5.account_info())