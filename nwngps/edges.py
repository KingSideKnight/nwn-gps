"""What kind of area change was that? Rules shared by the recorder, router and world map.

A loading screen looks the same whether you walked through a door, took a portal, cast
Teleport, died, or a DM moved you. Telling them apart:

  walk     left within DOOR_NEAR of a door / map pin, or within EDGE_NEAR of the area's edge
  portal   the same, but onto another server of the same world
  jump     left from anywhere else: a spell, a recall stone, a scripted portal, a DM, a
           graveyard respawn... Recorded but not routed until it has been taken from the same
           spot JUMP_CONFIRM times (a real portal gets reused; spells are cast from anywhere).
           If a door or pin turns up there later, it is promoted to walk/portal.
  death    arrived in a death area (settings "death_areas", e.g. Arelith's Fugue Plane).
           Never routed: "die here to get there" isn't directions.
  respawn  left a death area. Routed (it's how you get out), but no way back is assumed.

The router assumes a way back only for walk and portal, and only when you came out next to a
door, pin or map edge (natural_arrival): a portal that drops you mid-area has no way back there.
"""
import math

DOOR_NEAR = 4.0       # metres: real doors / transition pins were all within 2.6 m (Cordor, 15 links)
EDGE_NEAR = 6.0       # metres: walking off the map edge (seen at 1.2 m)
JUMP_CONFIRM = 3      # sightings from the same spot before a jump is trusted for routing
ARRIVE_NEAR = 6.0     # metres: through a door or off the map edge you arrive this close to the way
                      # back (every walked link seen: within 5 m); a portal or teleport that drops
                      # you in the middle of an area (seen: 10 and 28 m) has no way back there

KINDS = ("walk", "portal", "jump", "death", "respawn")
REVERSIBLE = {"walk", "portal"}
NEVER_ROUTED = {"death"}


def is_death_area(name, resref, patterns):
    """True if the area's name or resref contains any of the (case-insensitive) patterns."""
    hay = f"{name or ''}\n{resref or ''}".lower()
    return any(p and str(p).lower() in hay for p in patterns or ())


def edge_distance(x, y, size_tiles):
    """Metres from (x, y) to the nearest edge of an area of (w, h) tiles; None if unknown."""
    if not size_tiles or not all(isinstance(v, int) and v > 0 for v in size_tiles):
        return None
    w, h = size_tiles[0] * 10.0, size_tiles[1] * 10.0
    return min(x, w - x, y, h - y)


def natural_exit(x, y, size_tiles, nearest_poi_dist):
    """Did you leave by a door / pin / the map edge (rather than from the middle of nowhere)?"""
    if nearest_poi_dist is not None and nearest_poi_dist <= DOOR_NEAR:
        return True
    e = edge_distance(x, y, size_tiles)
    return e is not None and e <= EDGE_NEAR


def natural_arrival(x, y, size_tiles, nearest_poi_dist):
    """Did you come out next to a door / pin / the map edge, where a way back would be? None if we
    can't tell (area size unknown and no doors or pins recorded there)."""
    e = edge_distance(x, y, size_tiles)
    if e is None and nearest_poi_dist is None:
        return None
    return ((nearest_poi_dist is not None and nearest_poi_dist <= ARRIVE_NEAR)
            or (e is not None and e <= ARRIVE_NEAR))


def classify(prev_area, prev_name, prev_pos, prev_size, prev_server,
             new_area, new_name, new_server, nearest_poi_dist, death_patterns):
    """(kind, confirmed) for an area change seen without a relog in between."""
    if is_death_area(new_name, new_area, death_patterns):
        return "death", False
    if is_death_area(prev_name, prev_area, death_patterns):
        return "respawn", True
    if natural_exit(prev_pos[0], prev_pos[1], prev_size, nearest_poi_dist):
        return ("walk" if prev_server == new_server else "portal"), True
    return "jump", False


def dist(ax, ay, bx, by):
    return math.hypot(ax - bx, ay - by)
