"""Bound single-GPU hosts so scheduling and quota accounting use the same size."""

from typing import Literal

from coworld.runner.resource_quantity import parse_resource_quantity as parse_quantity
from coworld.types import CoworldResourceRequests

GPU_POOL_LABEL = "softmax.com/gpu-pool"
GPU_ALLOCATION_LABEL = "softmax.com/gpu-allocation"
GPU_FEATURED_TAINT = "softmax.com/featured-gpu"
GPU_INSTANCE_CPUS = {"g5.xlarge": 4, "g6.xlarge": 4, "g5.2xlarge": 8, "g6.2xlarge": 8}


def gpu_host_vcpus(requests: CoworldResourceRequests, *, role: Literal["game", "player"]) -> int:
    if requests.gpu is None:
        if requests.instance_type is not None and requests.instance_type.split(".")[0].startswith(("g", "p", "vt")):
            raise ValueError("GPU instance placement requires a GPU request")
        return 0
    cpu = parse_quantity(requests.cpu or "0")
    memory = parse_quantity(requests.memory or "0")
    # Leave space for Kubernetes, the coordinator, and injected sidecars.
    minimum = 4 if role == "player" and cpu <= 3 and memory <= parse_quantity("12Gi") else 8
    if cpu > 6 or memory > parse_quantity("24Gi"):
        raise ValueError("GPU runnables support at most 6 CPUs and 24Gi memory")
    if requests.instance_type is not None:
        if requests.instance_type not in GPU_INSTANCE_CPUS:
            raise ValueError("GPU instance type must be g5/g6.xlarge or g5/g6.2xlarge")
        selected = GPU_INSTANCE_CPUS[requests.instance_type]
        if selected < minimum:
            raise ValueError("GPU instance type is too small for this runnable and platform overhead")
        return selected
    return minimum
