# emit.py

def emit_event(event_type, details):
    """
    Create a structured event dictionary.
    """
    return {
        "type": event_type,
        "details": details
    }

if __name__ == "__main__":
    sample = emit_event("customer_enter", {"zone": "Dermedics"})
    print(sample)

