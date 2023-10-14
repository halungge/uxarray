import numpy as np
from uxarray.grid.coordinates import node_lonlat_rad_to_xyz
from uxarray.constants import INT_DTYPE, INT_FILL_VALUE, ERROR_TOLERANCE
from uxarray.grid.connectivity import close_face_nodes
from uxarray.grid.intersections import gca_gca_intersection
import warnings

POLE_POINTS = {
    'North': np.array([0.0, 0.0, 1.0]),
    'South': np.array([0.0, 0.0, -1.0])
}


def _grid_to_polygons(grid, correct_antimeridian_polygons=True):
    """Constructs an array of Shapely Polygons representing each face, with
    antimeridian polygons split according to the GeoJSON standards.

     Parameters
    ----------
    grid : uxarray.Grid
        Grid Object
    correct_antimeridian_polygons: bool, Optional
        Parameter to select whether to correct and split antimeridian polygons

    Returns
    -------
    polygons : np.ndarray
        Array containing Shapely Polygons
    """

    # import optional dependencies
    import antimeridian
    from shapely import polygons as Polygons

    # obtain polygon shells for shapely polygon construction
    polygon_shells = _build_polygon_shells(grid.Mesh2_node_x.values,
                                           grid.Mesh2_node_y.values,
                                           grid.Mesh2_face_nodes.values,
                                           grid.nMesh2_face,
                                           grid.nMaxMesh2_face_nodes,
                                           grid.nNodes_per_face.values)

    # list of shapely Polygons representing each face in our grid
    polygons = Polygons(polygon_shells)

    # handle antimeridian polygons, if any
    if grid.antimeridian_face_indices is not None and correct_antimeridian_polygons:

        # obtain each antimeridian polygon
        antimeridian_polygons = polygons[grid.antimeridian_face_indices]

        # correct each antimeridian polygon
        corrected_polygons = [
            antimeridian.fix_polygon(P) for P in antimeridian_polygons
        ]

        # insert correct polygon back into original array
        for i in reversed(grid.antimeridian_face_indices):
            polygons[i] = corrected_polygons.pop()

    return polygons


def _build_polygon_shells(Mesh2_node_x, Mesh2_node_y, Mesh2_face_nodes,
                          nMesh2_face, nMaxMesh2_face_nodes, nNodes_per_face):
    """Constructs the shell of each polygon derived from the closed off face
    nodes, which can be used to construct Shapely Polygons.

    Coordinates should be in degrees, with the longitude being in the
    range [-180, 180].
    """

    # close face nodes to construct closed polygons
    closed_face_nodes = close_face_nodes(Mesh2_face_nodes, nMesh2_face,
                                         nMaxMesh2_face_nodes)

    # additional node after closing our faces
    nNodes_per_face_closed = nNodes_per_face + 1

    # longitude should be between [-180, 180]
    if Mesh2_node_x.max() > 180:
        Mesh2_node_x = (Mesh2_node_x + 180) % 360 - 180

    polygon_shells = []
    for face_nodes, max_n_nodes in zip(closed_face_nodes,
                                       nNodes_per_face_closed):

        polygon_x = np.empty_like(face_nodes, dtype=Mesh2_node_x.dtype)
        polygon_y = np.empty_like(face_nodes, dtype=Mesh2_node_x.dtype)

        polygon_x[0:max_n_nodes] = Mesh2_node_x[face_nodes[0:max_n_nodes]]
        polygon_y[0:max_n_nodes] = Mesh2_node_y[face_nodes[0:max_n_nodes]]

        polygon_x[max_n_nodes:] = polygon_x[0]
        polygon_y[max_n_nodes:] = polygon_y[0]

        cur_polygon_shell = np.array([polygon_x, polygon_y])
        polygon_shells.append(cur_polygon_shell.T)

    return np.array(polygon_shells)


# TODO: Update this one
def _build_corrected_polygon_shells(polygon_shells):
    """Constructs ``corrected_polygon_shells`` and
    ``Grid.original_to_corrected), representing the polygon shells, with
    antimeridian polygons split.

     Parameters
    ----------
    grid : uxarray.Grid
        Grid Object

    Returns
    -------
    corrected_polygon_shells : np.ndarray
        Array containing polygon shells, with antimeridian polygons split
    _corrected_shells_to_original_faces : np.ndarray
        Original indices used to map the corrected polygon shells to their entries in face nodes
    """

    # import optional dependencies
    import antimeridian
    from shapely import Polygon

    # list of shapely Polygons representing each Face in our grid
    polygons = [Polygon(shell) for shell in polygon_shells]

    # List of Polygons (non-split) and MultiPolygons (split across antimeridian)
    corrected_polygons = [antimeridian.fix_polygon(P) for P in polygons]

    _corrected_shells_to_original_faces = []
    corrected_polygon_shells = []

    for i, polygon in enumerate(corrected_polygons):

        # Convert MultiPolygons into individual Polygon Vertices
        if polygon.geom_type == "MultiPolygon":
            for individual_polygon in polygon.geoms:
                corrected_polygon_shells.append(
                    np.array([
                        individual_polygon.exterior.coords.xy[0],
                        individual_polygon.exterior.coords.xy[1]
                    ]).T)
                _corrected_shells_to_original_faces.append(i)

        # Convert Shapely Polygon into Polygon Vertices
        else:
            corrected_polygon_shells.append(
                np.array([
                    polygon.exterior.coords.xy[0], polygon.exterior.coords.xy[1]
                ]).T)
            _corrected_shells_to_original_faces.append(i)

    original_to_corrected = np.array(_corrected_shells_to_original_faces,
                                     dtype=INT_DTYPE)

    return corrected_polygon_shells, _corrected_shells_to_original_faces


def _build_antimeridian_face_indices(grid):
    """Constructs ``antimeridian_face_indices``, which represent the indicies
    of faces that cross the antimeridian.

     Parameters
    ----------
    grid : uxarray.Grid
        Grid Object

    Returns
    -------
    antimeridian_face_indices : np.ndarray
        Array containing Shapely Polygons
    """
    polygon_shells = _build_polygon_shells(grid.Mesh2_node_x.values,
                                           grid.Mesh2_node_y.values,
                                           grid.Mesh2_face_nodes.values,
                                           grid.nMesh2_face,
                                           grid.nMaxMesh2_face_nodes,
                                           grid.nNodes_per_face.values)

    antimeridian_face_indices = np.argwhere(
        np.any(np.abs(np.diff(polygon_shells[:, :, 0])) >= 180, axis=1))

    # convert output into a 1D array
    if antimeridian_face_indices.shape[0] == 1:
        antimeridian_face_indices = antimeridian_face_indices[0]
    else:
        antimeridian_face_indices = antimeridian_face_indices.squeeze()
    return antimeridian_face_indices


def _grid_to_polygon_geodataframe(grid, correct_antimeridian_polygons=True):
    """Constructs and returns a ``spatialpandas.GeoDataFrame``"""

    # import optional dependencies
    from spatialpandas.geometry import MultiPolygonArray
    from spatialpandas import GeoDataFrame

    # obtain faces represented as polygons, corrected on the antimeridian
    polygons = _grid_to_polygons(grid, correct_antimeridian_polygons)

    # prepare geometry for GeoDataFrame
    geometry = MultiPolygonArray(polygons)

    # assign geometry
    gdf = GeoDataFrame({"geometry": geometry})

    return gdf


def _grid_to_matplotlib_polycollection(grid):
    """Constructs and returns a ``matplotlib.collections.PolyCollection``"""

    # import optional dependencies
    from matplotlib.collections import PolyCollection

    polygon_shells = _build_polygon_shells(grid.Mesh2_node_x.values,
                                           grid.Mesh2_node_y.values,
                                           grid.Mesh2_face_nodes.values,
                                           grid.nMesh2_face,
                                           grid.nMaxMesh2_face_nodes,
                                           grid.nNodes_per_face.values)

    corrected_polygon_shells, corrected_to_original_faces = _build_corrected_polygon_shells(
        polygon_shells)

    return PolyCollection(corrected_polygon_shells), corrected_to_original_faces


def _grid_to_matplotlib_linecollection(grid):
    """Constructs and returns a ``matplotlib.collections.LineCollection``"""

    # import optional dependencies
    from matplotlib.collections import LineCollection

    # obtain corrected shapely polygons
    polygons = grid.to_shapely_polygons(correct_antimeridian_polygons=True)

    # Convert polygons into lines
    lines = []
    for pol in polygons:
        boundary = pol.boundary
        if boundary.geom_type == 'MultiLineString':
            for line in list(boundary.geoms):
                lines.append(np.array(line.coords))
        else:
            lines.append(np.array(boundary.coords))

    # need transform? consider adding it later if needed
    return LineCollection(lines)


def _is_pole_point_inside_polygon(pole, face_edge_cart):
    """Determines if a pole point is inside a polygon. For notice: if the pole
    point is on the edge of the polygon, our function will consider it as
    "inside the polygon". To use this function, the given face cannot reach out
    the other hemisphere. For example, if you want to check if the North pole
    is inside a polygon, the polygon should not reach the south hemisphere.

    Parameters
    ----------
    pole : str
        Either 'North' or 'South'
    face_edge_cart : np.ndarray
        Face polygon that is represented by a list of edges in Cartesian coordinates.
        The shape of the array is (n_edges, 2, 3)

    Returns
    -------
    bool
        True if pole point is inside polygon, False otherwise.

    Raises
    ------
    ValueError
        If the provided pole point is neither 'North' nor 'South'.

    Warning
    -----
    UserWarning
        To use this function, the given face cannot reach out the other hemisphere. For example, if you
        want to check if the North pole is inside a polygon, the polygon should not reach the south hemisphere.
    """

    if pole not in POLE_POINTS:
        raise ValueError('Pole point must be either "North" or "South"')

    # Run a test for each vertice of the face to see if this face is: completely in the North hemisphere, go cross the
    # equator, or completely in the South hemisphere.

    # If the z coordinate of all vertices are positive, then the face is completely in the North hemisphere
    if np.all(face_edge_cart[:, :, 2] > 0.0):
        side = 'North'
    # If the z coordinate of all vertices are negative, then the face is completely in the South hemisphere
    elif np.all(face_edge_cart[:, :, 2] < 0.0):
        side = 'South'
    else:
        side = "cross"

    # If the face is not completely in the North or South hemisphere, we split the face into two faces, and run the
    # function recursively
    if side == "cross":
        # Split the face into two faces
        # First, find the edge that crosses the equator
        for i, edge in enumerate(face_edge_cart):
            if edge[0][2] * edge[1][2] < 0.0:
                # We found the edge that crosses the equator
                # We split the face into two faces
                face_edge_cart_1 = np.concatenate(
                    (face_edge_cart[:i], np.array([edge])), axis=0)
                face_edge_cart_2 = np.concatenate(
                    (np.array([edge]), face_edge_cart[i + 1:]), axis=0)
                # Run the function recursively
                return _is_pole_point_inside_polygon(pole,
                                                     face_edge_cart_1) or _is_pole_point_inside_polygon(
                                                         pole, face_edge_cart_2)

    else:
        # If the face is completely in the North or South hemisphere, we check if the pole point is in the same
        # hemisphere
        if pole != side:
            return False
        pole_point = POLE_POINTS[pole]
        ref_point = node_lonlat_rad_to_xyz(np.array(
            [0.0, 0.0]))  # We just set the reference point to be on the equator

        GCA = np.array([pole_point, ref_point])

        # Count the intersection point if: there's an intersection point and the intersection point is not the pole point
        intersection_count = 0

        for edge in face_edge_cart:
            intersection_point = gca_gca_intersection(GCA, edge)

            # If the intersection point is the pole point, we consider it still "inside the polygon"
            if intersection_point.size != 0:
                if np.allclose(intersection_point, pole_point, atol=ERROR_TOLERANCE):
                    return True
                intersection_count += 1

        return intersection_count % 2 != 0
