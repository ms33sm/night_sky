#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec 29 11:47:30 2025

@author: 
    
    from: https://stackoverflow.com/questions/48272430/convert-image-into-tiles-with-xyz-url-open-layers
    
"""

import os
from PIL import Image

Image.MAX_IMAGE_PIXELS = None #933120000


# make sure we can run this script from wherever and not screw up our paths
base_path = os.path.dirname(__file__)

# where we get our image that we chop up
tile_source_path = os.path.join(base_path, "../starmap_2020_32k_8bit_stretch.png")

# where we put our chopped up images
tile_gen_path = os.path.join(base_path, "tiles")

MIN_ZOOM = 0
MAX_ZOOM = 7

TILE_SIZE = 512 # width and height of each tile

with Image.open(tile_source_path) as orig_world_map:
    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        if z == 0:
            print ("Zoom level", z, "- Generating", 2 ** z * 2 ** z, TILE_SIZE, "x", TILE_SIZE, "images")
        else:
            print ("Zoom level", z, "- Generating", 2 ** z * 2 ** z, TILE_SIZE, "x", TILE_SIZE, "images")

        tiles_per_dimension = 2 ** (z+1)
        # Zoom the world map to be big enough for the number of tiles given the size of the tiles
        zoomed_world_map = orig_world_map.resize((
            (tiles_per_dimension) * TILE_SIZE,
            int(tiles_per_dimension/2) * TILE_SIZE,
        ))
        for y in range(int(tiles_per_dimension/2)):
            # Make the dir representing this value of x, within the dir
            # representing the zoom level z. Values of y are represented
            # by the files within this dir:
            # /tiles/{z}/{y}/{x}.png
            y_name=str(format(y, '06'))
            x_val_dir = os.path.join(tile_gen_path, str(z), y_name)
            if not os.path.exists(x_val_dir):
                os.makedirs(x_val_dir)
            for x in range(tiles_per_dimension):
                cropped = zoomed_world_map.crop((
                    x * TILE_SIZE,
                    y * TILE_SIZE,
                    (x + 1) * TILE_SIZE - 1,
                    (y + 1) * TILE_SIZE - 1,
                ))
                print(z, x,y)
                # print( x * TILE_SIZE, y * TILE_SIZE, (x + 1) * TILE_SIZE - 1, (y + 1) * TILE_SIZE - 1)
                x_name=str(format(x, '06'))
                cropped.save(os.path.join(x_val_dir, y_name+"_"+x_name + ".jpg"))
        # free memory
        zoomed_world_map = None
        del zoomed_world_map

# import os
# from PIL import Image

# # make sure we can run this script from wherever and not screw up our paths
# base_path = os.path.dirname(__file__)

# # where we get our image that we chop up
# tile_source_path = os.path.join(base_path, "starmap_2020_8k_8bit_stretch.jpg")

# # where we put our chopped up images
# tile_gen_path = os.path.join(base_path, "tiles")

# MIN_ZOOM = 0
# MAX_ZOOM = 1

# with Image.open(tile_source_path) as orig:
#     for z in range(MIN_ZOOM, MAX_ZOOM + 1):
#         if z == 0:
#             print ("Zoom level", z, "- Generating", 2 ** z * 2 ** z, "256x256 image")
#         else:
#             print ("Zoom level", z, "- Generating", 2 ** z * 2 ** z, "256x256 images")
#         for x in range(2 ** z):
#             # Make the dir representing this value of x, within the dir
#             # representing the zoom level z. Values of y are represented
#             # by the files within this dir:
#             # /tiles/{z}/{x}/{y}.png
#             x_val_dir = os.path.join(tile_gen_path, str(z), str(x))
#             if not os.path.exists(x_val_dir):
#                 os.makedirs(x_val_dir)
#             for y in range(2 ** z):
#                 max_val = 1024
#                 size = 1024 * (2 ** (-z))
#                 assert size == int(size)
#                 size = int(size)
#                 resized = orig.resize(
#                     (256, 256),
#                     box=(
#                         x * size,
#                         y * size,
#                         (x + 1) * size - 1,
#                         (y + 1) * size - 1,
#                     )
#                 )
#                 resized.save(os.path.join(x_val_dir, str(y) + ".png"))