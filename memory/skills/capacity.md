# Capacity Rules

Fetch current capacity for every proposed factory. Do not infer current capacity from memory.
The required quantity must fit available capacity. Respect the maximum of ECN and process lead times.
When no factory fits, return a blocked proposal. Do not shift capacity away from other commitments.
Changing quantity, costs, source versions or design constraints invalidates earlier approval.
