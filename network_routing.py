"""
Calcul de temps de trajet sans moteur de routage externe (OSRM/ORS),
en s'appuyant uniquement sur qgis.analysis, livré avec QGIS.

Principe : on construit un graphe pondéré à partir d'une couche de lignes
(réseau routier/cyclable) déjà disponible localement (OpenStreetMap extrait
en amont avec QGIS/osmconvert, ou tout autre référentiel type BD TOPO),
puis on calcule le plus court chemin en temps avec Dijkstra (intégré à QGIS,
pas de dépendance externe).

Un même graphe peut servir pour plusieurs modes (voiture, vélo) en changeant
uniquement la vitesse associée à chaque tronçon.
"""
from qgis.core import QgsPointXY, QgsDistanceArea, QgsUnitTypes
from qgis.analysis import (
    QgsVectorLayerDirector,
    QgsNetworkSpeedStrategy,
    QgsNetworkDistanceStrategy,
    QgsGraphBuilder,
    QgsGraphAnalyzer,
)


def build_offline_graph(network_layer, speed_field=None, default_speed_kmh=40.0, crs=None):
    """
    Construit un graphe routable à partir d'une couche de lignes QGIS.

    - network_layer : couche vecteur de lignes (ex: routes extraites d'OSM
      localement avec QGIS -> Vecteur -> OSM, ou tout référentiel local).
    - speed_field : nom d'un champ contenant la vitesse (km/h) par tronçon,
      si disponible (ex: champ 'maxspeed' d'un export OSM). Sinon, vitesse
      unique `default_speed_kmh` appliquée à tout le réseau (approximation,
      mais qui suffit pour comparer des itinéraires entre eux).
    - crs : CRS métrique à utiliser pour les distances (ex: Lambert-93 en
      France) ; indispensable si network_layer est en WGS84 (EPSG:4326).
    """
    director = QgsVectorLayerDirector(
        network_layer,
        -1,          # pas de champ de sens de circulation (bidirectionnel)
        "", "", "",  # champs sens direct/inverse/les deux (non utilisés ici)
        QgsVectorLayerDirector.DirectionBoth,
    )

    if speed_field is not None:
        field_idx = network_layer.fields().indexFromName(speed_field)
        strategy = QgsNetworkSpeedStrategy(field_idx, default_speed_kmh, 0.0)
    else:
        # QgsNetworkDistanceStrategy : coût = distance ; on convertira
        # nous-mêmes en temps avec default_speed_kmh (cf. shortest_path_minutes)
        strategy = QgsNetworkDistanceStrategy()

    director.addStrategy(strategy)

    builder = QgsGraphBuilder(crs or network_layer.sourceCrs())
    director.makeGraph(builder, [])  # pas de points additionnels ici
    graph = builder.graph()
    return graph, builder, strategy, isinstance(strategy, QgsNetworkDistanceStrategy)


def shortest_path_minutes(graph, builder, is_distance_based, origin_xy: QgsPointXY,
                            destination_xy: QgsPointXY, speed_kmh: float = 40.0):
    """
    Calcule le temps de trajet (en minutes) entre deux points via le graphe
    construit par build_offline_graph().

    origin_xy / destination_xy doivent être dans le même CRS que le graphe.
    """
    tied_origin = builder.graph().findVertex(origin_xy) if hasattr(builder, "findVertex") else None

    # Rattachement des points au réseau (snap au tronçon le plus proche)
    tied_points = builder.tiePoint(origin_xy), builder.tiePoint(destination_xy)
    idx_origin = graph.findVertex(tied_points[0])
    idx_dest = graph.findVertex(tied_points[1])

    if idx_origin < 0 or idx_dest < 0:
        return None  # points non rattachables au réseau (couche incomplète)

    tree, costs = QgsGraphAnalyzer.dijkstra(graph, idx_origin, 0)
    if idx_dest >= len(costs) or tree[idx_dest] == -1 and idx_origin != idx_dest:
        return None  # pas de chemin trouvé

    cost = costs[idx_dest]  # en mètres si distance-based, en "coût vitesse" sinon

    if is_distance_based:
        # cost = distance en mètres -> conversion en minutes via vitesse moyenne
        return (cost / 1000.0) / speed_kmh * 60.0
    else:
        # QgsNetworkSpeedStrategy renvoie déjà un coût en secondes
        return cost / 60.0


def straight_line_time_minutes(origin_xy: QgsPointXY, destination_xy: QgsPointXY,
                                  speed_kmh: float, ellipsoid_crs=None, detour_factor: float = 1.3):
    """
    Solution de dernier recours (dégradée) : temps estimé à partir de la
    distance à vol d'oiseau, majorée d'un facteur de détour routier
    (1.3 est une valeur usuelle en zone rurale ; à calibrer si possible en
    comparant à quelques temps réels connus, cf. section validation).

    N'utiliser que si aucune couche de réseau exploitable n'est disponible :
    c'est nettement moins fiable qu'un vrai plus court chemin sur graphe.
    """
    d = QgsDistanceArea()
    if ellipsoid_crs:
        d.setEllipsoid(ellipsoid_crs)
    dist_m = d.measureLine(origin_xy, destination_xy)
    dist_km = d.convertLengthMeasurement(dist_m, QgsUnitTypes.DistanceKilometers)
    return (dist_km * detour_factor) / speed_kmh * 60.0
