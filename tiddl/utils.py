import re
import os
import ffmpeg
import logging

from pydantic import BaseModel
from urllib.parse import urlparse
from pathlib import Path

from typing import Literal, get_args

from tiddl.models.constants import TrackQuality, QUALITY_TO_ARG
from tiddl.models.resource import Track

ResourceTypeLiteral = Literal["track", "album", "playlist", "artist"]


class TidalResource(BaseModel):
    type: ResourceTypeLiteral
    id: str

    @property
    def url(self) -> str:
        return f"https://listen.tidal.com/{self.type}/{self.id}"

    @classmethod
    def fromString(cls, string: str):
        """
        Extracts the resource type (e.g., "track", "album")
        and resource ID from a given input string.

        The input string can either be a full URL or a shorthand string
        in the format `resource_type/resource_id` (e.g., `track/12345678`).
        """

        path = urlparse(string).path
        resource_type, resource_id = path.split("/")[-2:]

        if resource_type not in get_args(ResourceTypeLiteral):
            raise ValueError(f"Invalid resource type: {resource_type}")

        if not resource_id.isdigit() and resource_type != "playlist":
            raise ValueError(f"Invalid resource id: {resource_id}")

        return cls(type=resource_type, id=resource_id)  # type: ignore

    def __str__(self) -> str:
        return f"{self.type}/{self.id}"


def sanitizeString(string: str) -> str:
    pattern = r'[\\/:"*?<>|]+'
    return re.sub(pattern, "", string)


def formatTrack(
    template: str,
    track: Track,
    album_artist="",
    playlist_title="",
    playlist_index=0,
) -> str:
    artist = sanitizeString(track.artist.name) if track.artist else ""
    features = [
        sanitizeString(track_artist.name)
        for track_artist in track.artists
        if track_artist.name != artist
    ]

    track_dict = {
        "id": str(track.id),
        "title": sanitizeString(track.title),
        "version": sanitizeString(track.version or ""),
        "artist": artist,
        "artists": ", ".join(features + [artist]),
        "features": ", ".join(features),
        "album": sanitizeString(track.album.title),
        "number": track.trackNumber,
        "disc": track.volumeNumber,
        "date": (track.streamStartDate if track.streamStartDate else ""),
        # i think we can remove year as we are able to format date
        "year": track.streamStartDate.strftime("%Y") if track.streamStartDate else "",
        "playlist": sanitizeString(playlist_title),
        "bpm": track.bpm or "",
        "quality": QUALITY_TO_ARG[track.audioQuality],
        "album_artist": sanitizeString(album_artist),
        "playlist_number": playlist_index or 0,
    }

    formatted_track = template.format(**track_dict)

    disallowed_chars = r'[\\:"*?<>|]+'
    invalid_chars = re.findall(disallowed_chars, formatted_track)

    if invalid_chars:
        raise ValueError(
            f"Template '{template}' and formatted track '{formatted_track}' contains disallowed characters: {' '.join(sorted(set(invalid_chars)))}"
        )

    return formatted_track


def trackExists(
    track_quality: TrackQuality, download_quality: TrackQuality, file_name: Path
):
    """
    Predict track extension and check if track file exists.
    """

    FLAC_QUALITIES: list[TrackQuality] = ["LOSSLESS", "HI_RES_LOSSLESS"]

    if download_quality in FLAC_QUALITIES and track_quality in FLAC_QUALITIES:
        extension = ".flac"
    else:
        extension = ".m4a"

    full_file_name = file_name.with_suffix(extension)

    return full_file_name.exists()


def convertFileExtension(
    source_file: Path, extension: str, remove_source=False, is_video=False
) -> Path:
    """
    Converts `source_file` extension and returns `Path` of file with new `extension`.

    Removes `source_file` when `remove_source` is truthy.
    """

    try:
        output_file = source_file.with_suffix(extension)
    except ValueError as e:
        logging.error(e)
        return source_file

    logging.debug((source_file, output_file, extension))

    if extension == source_file.suffix:
        return source_file
    
    ffmpeg_args = {"c:a": "copy", "loglevel": "error"}

    if is_video:
        ffmpeg_args["c:v"] = "copy"

    ffmpeg.input(str(source_file)).output(
        str(output_file), **ffmpeg_args
    ).run(overwrite_output=1)

    if remove_source:
        os.remove(source_file)

    return output_file
