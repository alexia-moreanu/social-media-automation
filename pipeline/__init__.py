"""Happy Place posting pipeline."""

# iPhone photos in Drive are HEIC; register the decoder once for every module.
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:  # pragma: no cover - the pipeline still works for JPEG/PNG
    pass
