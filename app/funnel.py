# funnel.py

def funnel_stages(events):
    """
    Input: list of events
    Output: funnel counts
    """
    stages = {"enter": 0, "browse": 0, "checkout": 0}
    for e in events:
        if e["type"] in stages:
            stages[e["type"]] += 1
    return stages

if __name__ == "__main__":
    sample_events = [
        {"type": "enter"}, {"type": "browse"}, {"type": "browse"}, {"type": "checkout"}
    ]
    print(funnel_stages(sample_events))
