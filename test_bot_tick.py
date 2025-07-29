import sys
import traceback
from exchange import get_exchange

# This script is for debugging the initialization process.

def main():
    try:
        print("Attempting to initialize exchange...")
        exchange = get_exchange()
        if exchange:
            print("Exchange initialized successfully.")
            print(f"Exchange ID: {exchange.id}")
        else:
            print("Exchange initialization failed, returned None.")
    except Exception as e:
        print("--- AN ERROR OCCURRED DURING EXCHANGE INITIALIZATION ---")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {e}")
        print("\n--- TRACEBACK ---")
        traceback.print_exc(file=sys.stdout)
        print("----------------------------------------------------")

if __name__ == "__main__":
    main()
