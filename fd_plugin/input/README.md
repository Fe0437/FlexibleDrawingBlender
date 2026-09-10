# Blender input

This package converts Blender mouse and pen events into engine input samples.
It preserves whether each position is measured, coalesced, or predicted so that
temporary predictions never become final canvas work.

Blender reports saved intermediate tablet positions as `INBETWEEN_MOUSEMOVE`
events before the following `MOUSEMOVE`. The engine calls those intermediate
positions coalesced samples. Blender does not supply predicted samples.
