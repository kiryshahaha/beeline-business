"""VRPTW Solver using Google OR-Tools."""

from ortools.constraint_solver import pywrapcp
from ortools.constraint_solver import routing_enums_pb2

from app.modules.solver.schemas import Route, SolveRequest, SolveResponse, Step


class VRPTWSolver:
    def __init__(self, data: SolveRequest):
        self.data = data

    def solve(self) -> SolveResponse:
        manager = pywrapcp.RoutingIndexManager(
            len(self.data.time_matrix),
            self.data.num_vehicles,
            self.data.starts,
            self.data.ends,
        )
        routing = pywrapcp.RoutingModel(manager)

        def time_callback(from_index: int, to_index: int) -> int:
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            # Travel time + service time at the 'from_node'
            return self.data.time_matrix[from_node][to_node] + self.data.service_times[from_node]

        transit_callback_index = routing.RegisterTransitCallback(time_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        # Time dimension
        time = "Time"
        routing.AddDimension(
            transit_callback_index,
            120,  # slack_max (max waiting time)
            14400,  # capacity (large enough to fit any time window within a day or more)
            False,  # fix_start_cumul_to_zero
            time,
        )
        time_dimension = routing.GetDimensionOrDie(time)

        # Time windows
        for node_idx, time_window in enumerate(self.data.time_windows):
            index = manager.NodeToIndex(node_idx)
            if len(time_window) >= 2:
                time_dimension.CumulVar(index).SetRange(time_window[0], time_window[1])
            elif len(time_window) == 1:
                time_dimension.CumulVar(index).SetRange(time_window[0], 14400)
                
        # Time windows for End nodes (since NodeToIndex only maps to Start nodes)
        for v in range(self.data.num_vehicles):
            end_node_idx = self.data.ends[v]
            time_window = self.data.time_windows[end_node_idx]
            end_index = routing.End(v)
            if len(time_window) >= 2:
                time_dimension.CumulVar(end_index).SetRange(time_window[0], time_window[1])
            elif len(time_window) == 1:
                time_dimension.CumulVar(end_index).SetRange(time_window[0], 14400)

        # Allowed vehicles (Hard Constraints)
        if self.data.allowed_vehicles:
            for node_str, allowed_list in self.data.allowed_vehicles.items():
                if not node_str.isdigit():
                    continue
                node_idx = int(node_str)
                if node_idx < 0 or node_idx >= len(self.data.time_matrix):
                    continue
                index = manager.NodeToIndex(node_idx)
                vehicle_var = routing.VehicleVar(index)
                for v in range(self.data.num_vehicles):
                    if v not in allowed_list:
                        vehicle_var.RemoveValue(v)

        # Dropping visits (Penalties)
        for node_idx in range(len(self.data.penalties)):
            # Skip start and end nodes, as they cannot be dropped
            if node_idx in self.data.starts or node_idx in self.data.ends:
                continue
            index = manager.NodeToIndex(node_idx)
            penalty = self.data.penalties[node_idx]
            routing.AddDisjunction([index], penalty)

        # Search parameters
        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.seconds = 3

        # Solve
        assignment = routing.SolveWithParameters(search_parameters)

        if not assignment:
            return SolveResponse(
                status="NOT_SOLVED", routes=[], dropped_nodes=[], total_cost=0
            )

        status_str = "OPTIMAL"

        routes = []
        for vehicle_id in range(self.data.num_vehicles):
            index = routing.Start(vehicle_id)
            steps = []
            while not routing.IsEnd(index):
                time_var = time_dimension.CumulVar(index)
                node_idx = manager.IndexToNode(index)
                steps.append(Step(node=node_idx, arrival_time=assignment.Min(time_var)))
                index = assignment.Value(routing.NextVar(index))

            # Add end node
            time_var = time_dimension.CumulVar(index)
            node_idx = manager.IndexToNode(index)
            steps.append(Step(node=node_idx, arrival_time=assignment.Min(time_var)))

            routes.append(Route(vehicle_id=vehicle_id, steps=steps))

        dropped_nodes = []
        for node_idx in range(len(self.data.time_matrix)):
            # Skip start and end nodes
            if node_idx in self.data.starts or node_idx in self.data.ends:
                continue
            index = manager.NodeToIndex(node_idx)
            if assignment.Value(routing.NextVar(index)) == index:
                dropped_nodes.append(node_idx)

        return SolveResponse(
            status=status_str,
            routes=routes,
            dropped_nodes=dropped_nodes,
            total_cost=assignment.ObjectiveValue(),
        )
