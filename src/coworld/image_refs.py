from __future__ import annotations


def is_digest_pinned_image_ref(image: str) -> bool:
    return "@sha256:" in image


def is_coworld_content_tag(image: str) -> bool:
    tag = _image_tag(image)
    return tag is not None and tag.startswith("coworld-")


def is_mutable_registry_image_ref(image: str) -> bool:
    if is_digest_pinned_image_ref(image) or is_coworld_content_tag(image):
        return False
    return _has_registry_host(image)


def image_ref_without_tag(image: str) -> str:
    image = image.split("@", 1)[0]
    tag_separator = image.rfind(":")
    slash_separator = image.rfind("/")
    if tag_separator > slash_separator:
        return image[:tag_separator]
    return image


def _has_registry_host(image: str) -> bool:
    image = image.split("@", 1)[0]
    if "/" not in image:
        return False
    first_component = image.split("/", 1)[0]
    return "." in first_component or ":" in first_component or first_component == "localhost"


def _image_tag(image: str) -> str | None:
    image = image.split("@", 1)[0]
    tag_separator = image.rfind(":")
    slash_separator = image.rfind("/")
    if tag_separator > slash_separator:
        return image[tag_separator + 1 :]
    return None
