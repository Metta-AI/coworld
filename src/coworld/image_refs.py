from __future__ import annotations


def is_digest_pinned_image_ref(image: str) -> bool:
    return "@sha256:" in image


def is_coworld_content_tag(image: str) -> bool:
    image = image.split("@", 1)[0]
    tag_separator = image.rfind(":")
    return tag_separator > image.rfind("/") and image[tag_separator + 1 :].startswith("coworld-")


def is_mutable_registry_image_ref(image: str) -> bool:
    if is_digest_pinned_image_ref(image) or is_coworld_content_tag(image):
        return False
    image = image.split("@", 1)[0]
    first_component = image.split("/", 1)[0]
    return "/" in image and ("." in first_component or ":" in first_component or first_component == "localhost")


def image_ref_without_tag(image: str) -> str:
    image = image.split("@", 1)[0]
    tag_separator = image.rfind(":")
    return image[:tag_separator] if tag_separator > image.rfind("/") else image
