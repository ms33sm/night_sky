#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Dec 27 11:28:12 2025

@author: ms33sm

Workflow to make night_sky map for digiKam / Marble

Milky way picture downloaded from:
    download STAR map - top one (nice color of stars)
    https://svs.gsfc.nasa.gov/4851/
    link to poicture 8k (there are also bigger) https://svs.gsfc.nasa.gov/vis/a000000/a004800/a004851/milkyway_2020_8k.exr

export MAGICK_TMPDIR=/home/ms33sm/tmp/
convert -debug cache starmap_2020_32k.exr  -depth 8 starmap_2020_32k_8bit.png
convert -debug cache -contrast-stretch 0.5x0.5% starmap_2020_32k_8bit.png starmap_2020_32k_8bit_stretch.png

For json to kml - useful links
    https://stackoverflow.com/questions/71113897/converting-geojson-to-kml-using-python
    
    kml documentation / standars: https://docs.ogc.org/is/12-007r2/12-007r2.html
    
    
"""

from PIL import Image, ImageOps

from urllib.request import urlretrieve

import os
import pathlib
import subprocess
import sys


download_huge_files = True

# Track outcomes so the script can print a summary and exit non-zero on failures
generated = []
skipped = []
failed = []

download_folder="downloads"
results_folder="final"

if not os.path.exists(download_folder):
    os.makedirs(download_folder)

if not os.path.exists(results_folder):
    os.makedirs(results_folder)

Panorama_name=os.path.join(download_folder, "milkyway_2020_8k.exr")
panorama_final=os.path.join(results_folder, "mirrored.jpg")


clausule=os.path.join(download_folder, "BSD-3-Clause.html")
constellations_borders=os.path.join(download_folder, "constellations_borders.geojson")
constellations_lines=os.path.join(download_folder, "constellations_lines.geojson")
constellations=os.path.join(download_folder, "constellations.geojson")
dso_mag6=os.path.join(download_folder, "dsos.6.geojson")
stars_mag6=os.path.join(download_folder, "stars.6.geojson")


constellations_borders_mirror=os.path.join(results_folder, "constellations_borders_mirror.geojson")
constellations_lines_mirror=os.path.join(results_folder, "constellations_lines_mirror.geojson")
constellations_mirror=os.path.join(results_folder, "constellations_mirror.geojson")
dso_mag6_mirror=os.path.join(results_folder, "dsos_mag6_mirror.geojson")
stars_mag6_mirror=os.path.join(results_folder, "stars_6_mirror.geojson")

download_files=[
        [ clausule, "https://opensource.org/license/BSD-3-Clause"],
        [ Panorama_name, "https://svs.gsfc.nasa.gov/vis/a000000/a004800/a004851/milkyway_2020_8k.exr"],
        [ constellations_borders, "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/constellations.borders.geojson"], 
        [ constellations_lines, "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/constellations.lines.geojson"],
        [ constellations,       "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/constellations.geojson"],
        [ dso_mag6 , "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/dsos.6.geojson"],
        [ stars_mag6, "https://raw.githubusercontent.com/dieghernan/celestial_data/refs/heads/main/data/stars.6.geojson"],
    ]


### first file to process, second output file, third: icon filename under the theme's pics/ folder, 4th: KML color AABBGGRR, 5th: linewidth 2.5
mirror_geojson_files=[
    #### Multiline coordinate file
        [constellations_borders, constellations_borders_mirror, None, "FFFF00FF", 2.5],
        # [constellations_lines, constellations_lines_mirror],
    ]

mirror_geojson_files1=[
        # [constellations_borders, constellations_borders_mirror],
        [constellations_lines, constellations_lines_mirror, None, "FF0000FF", 2.5],
    ]

mirror_geojson_files2=[
    #### Point coordinate file
        # [constellations_borders, constellations_borders_mirror],
        [constellations, constellations_mirror, "pics/star.png", "FFFFFFFF", 2.5],
        [dso_mag6, dso_mag6_mirror, "pics/dso.png", "FFFFFFFF", 2.5],
        [stars_mag6, stars_mag6_mirror, "pics/star.png", "FFFFFFFF", 2.5],
    ]



##### download files
if download_huge_files:
    for item in download_files:
        target, url = item
        if os.path.exists(target) and os.path.getsize(target) > 0:
            print(f"[SKIP] already present: {target}")
            skipped.append(target)
            continue
        print(f"Downloading: {url}")
        print(f"         to: {target}")
        try:
            urlretrieve(url, target)
        except Exception as exc:
            # Some hosts (e.g. opensource.org) reject Python's user agent with HTTP 403
            # but accept curl's default one, so retry once with curl.
            print(f"[WARN] urllib failed for {target}: {type(exc).__name__}: {exc}")
            print("       retrying with curl")
            try:
                subprocess.run(
                    ["curl", "-fsSL", "--retry", "3", "-o", target, url],
                    check=True,
                )
            except Exception as curl_exc:
                print(f"[FAIL] download {target}: {type(curl_exc).__name__}: {curl_exc}")
                print("       hint: check the URL and your network connection; partial file will be removed")
                failed.append(target)
                try:
                    if os.path.exists(target):
                        os.remove(target)
                except OSError:
                    pass
                continue
        if not os.path.exists(target) or os.path.getsize(target) == 0:
            print(f"[FAIL] download {target}: file is missing or empty after download")
            failed.append(target)
        else:
            print(f"[OK] downloaded: {target}")
            generated.append(target)

# #### mirror panorama and save it as jpg file
# Best effort: if this fails, keep going and generate the KML files anyway.
try:
    from wand.image import Image as WandImage
except Exception as exc:
    print(f"[FAIL] {panorama_final}: cannot import wand: {type(exc).__name__}: {exc}")
    print("       hint: install with 'python3 -m pip install --user Wand' and make sure ImageMagick is installed")
    failed.append(panorama_final)
else:
    if not os.path.exists(Panorama_name) or os.path.getsize(Panorama_name) == 0:
        print(f"[FAIL] {panorama_final}: source panorama is missing or empty: {Panorama_name}")
        print("       hint: set download_huge_files = True or download the .exr panorama manually")
        failed.append(panorama_final)
    else:
        try:
            print(f"Creating: {panorama_final}")
            # The NASA panorama is a linear HDR EXR. Boost it in linear light and
            # then roll the highlights off with a Reinhard curve (u/(1+u)): the
            # faint stars stay above the noise floor while bright stars do not
            # clip to white. A plain brightness boost on the 8-bit JPEG instead
            # flattens the sky to grey.
            exposure = 100
            img = WandImage(filename=Panorama_name)
            # Wand reports the EXR as 16-bit sRGB; go to linear RGB first so the
            # multiply and the tone curve operate on physical light values.
            img.transform_colorspace('rgb')
            img.evaluate(operator='multiply', value=exposure)
            img.fx('u/(1+u)')
            img.transform_colorspace('srgb')
            img.format = 'jpeg'
            img.compression_quality = 95
            img.save(filename=panorama_final)
        except Exception as exc:
            print(f"[FAIL] {panorama_final}: {type(exc).__name__}: {exc}")
            print("       hint: check ImageMagick EXR/JPEG delegates, MAGICK_TMPDIR and free disk space")
            failed.append(panorama_final)
        else:
            if not os.path.exists(panorama_final) or os.path.getsize(panorama_final) == 0:
                print(f"[FAIL] {panorama_final}: output is missing or empty")
                failed.append(panorama_final)
            else:
                print(f"[OK] created: {panorama_final}")
                generated.append(panorama_final)



# for mirror_pair in mirror_geojson_files:

#     geojson_in=mirror_pair[0]
#     gojson_out=mirror_pair[1]

#     with open(geojson_in, 'r') as file_in:
#         geojson_data = geojson.load(file_in)
        

#     for feature in geojson_data['features']:
#         for point in feature['geometry']['coordinates'][0]:
#             point[0] = point[0]*(-1)
#             # print(point[0])
#     file_in.close()
#     with open(gojson_out, 'w') as file_out:
#         geojson.dump(geojson_data, file_out)
#     file_out.close()

# for mirror_pair in mirror_geojson_files1:

#     geojson_in=mirror_pair[0]
#     gojson_out=mirror_pair[1]

#     with open(geojson_in, 'r') as file_in:
#         geojson_data = geojson.load(file_in)
        

#     # for item in geojson_data['features']:
#     #     for i
#     #     item['geometry']['coordinates'][0]=(-1)*item['geometry']['coordinates'][0]
    
#     for item in geojson_data['features']:
#         cord = item['geometry']['coordinates']
#         for i in range(0, len(cord)):
#             for j in range(0, len(cord[i])):
#                 cord[i][j][0]=(-1)*cord[i][j][0]
#                 # for k in range(len(cord[i][j])):
#                 # print(k[0])
#                 # lats.append(k[1])
#                 # lons.append(k[0])
                
#     file_in.close()
#     with open(gojson_out, 'w') as file_out:
#         geojson.dump(geojson_data, file_out)
#     file_out.close()  
    
    
# for mirror_pair in mirror_geojson_files2:

#     geojson_in=mirror_pair[0]
#     gojson_out=mirror_pair[1]

#     with open(geojson_in, 'r') as file_in:
#         geojson_data = geojson.load(file_in)
        

#     for item in geojson_data['features']:
#         # geojson_data['features'][i]
#         item['geometry']['coordinates'][0]=(-1)*item['geometry']['coordinates'][0]
        
#     file_in.close()
#     with open(gojson_out, 'w') as file_out:
#         geojson.dump(geojson_data, file_out)
#     file_out.close()   
    
    
    
# Open with marble and save as kml file
# Include files in gdml file with path maps/earth/night_sky/abc.kml
# copy whole night_sky folder with edited dgml file to digikam folder matble_data/earth/...



# from pygeoif.factories import shape
# from pygeoif.geometry import Point
# # # import sys
# # import fastkml
# # import fastkml.containers
# # import fastkml.features
# # import fastkml.styles
# # from fastkml.geometry import create_kml_geometry
# # from fastkml.enums import AltitudeMode

# import pathlib
# import simplekml

# from simplekml import Kml, Color

# mirror_x_geometry = True

# allfiles = mirror_geojson_files + mirror_geojson_files1 + mirror_geojson_files2

# kml = Kml()
# multilin = kml.newmultigeometry()
# for mirror_pair in allfiles:
    
#     mirror_pair = allfiles[0]
    
#     geojson_in=mirror_pair[0]
#     gojson_out=mirror_pair[1]
#     icon_url = mirror_pair[2]
#     linecolor= mirror_pair[3]
#     linewidth= mirror_pair[4]
    
#     icon_scale=0.2
    
#     placemarks = []
#     with open(geojson_in, 'r') as file_in:
#         data = geojson.load(file_in)
#     for feature in data['features']:
        
#          geometry = shape(feature["geometry"])
         
#          if mirror_x_geometry:
#              if feature['geometry'].type == "Point":
#                  feature['geometry']['coordinates'][0] = (-1)*feature['geometry']['coordinates'][0]
#                  # for point in feature['geometry']['coordinates']:
#                  #     feature['geometry']['coordinates'][0] = point*(-1)
                     
#              elif feature['geometry'].type == "MultiLineString":
#                  cord = feature['geometry']['coordinates']
#                  for i in range(0, len(cord)):
#                     for j in range(0, len(cord[i])):
#                         cord[i][j][0]=(-1)*cord[i][j][0]
#              else: 
#                 print(f"Not supported geometry type: {feature['geometry'].type}")
                    
#          geometry = shape(feature["geometry"])
#          # print(geometry)
         
#          # geometry_old=geometry
#          # if mirror_x_geometry:
#          #     for gm in geometry.geoms:
#          #         for point in gm.geoms:
#          #             new_x = (-1)*point.x
#          #             p = Point(new_x, point.y)
#          #             point = shape(p)
#          # geometry = shape(feature["geometry"])
#          # kml_geometry = create_kml_geometry(
#          #     geometry,
#          #     tessellate=1,
#          #     # extrude=False,
#          #    # altitude_mode=AltitudeMode.relative_to_ground,
#          #    )
#          # # color = 4283782485
         
#          # style = fastkml.styles.Style(
#          #     styles=[
#          #         fastkml.styles.LineStyle(color=linecolor, width=linewidth),
#          #         fastkml.styles.PolyStyle(
#          #             color=linecolor,
#          #             # fill=True,
#          #             # outline=True,
#          #             ),
#          #         fastkml.styles.IconStyle(icon_href=icon_url, scale=icon_scale, color=linecolor),
#          #         ]
#          #     )
#          try:
#              name=feature["properties"]["name"]
#          except:
#              name=""
#              pass
#          if name is not None:
#              print(name)
         
#          coords=[]
#          for g in geometry.geoms:
#              coords.append(g.coords)
#              print(g.coords)
         
#          placemark = multilin.newlinestring(coords=feature['geometry']['coordinates'])
             
#          # placemark = fastkml.features.Placemark(
#          #     name = name,
#          #     # description=feature["properties"]["FORMAL_EN"],
#          #     kml_geometry=kml_geometry,
#          #     styles=[style],
#          # )
         
#          placemarks.append(placemark)
    
#     for place in placemarks:
#         pnt = kml.newpoint()
#     kml.save("test" + ".kml")
    
#     document = fastkml.containers.Document(features=placemarks)
#     kml = fastkml.KML(features=[document])
#     outfile = pathlib.Path(gojson_out + ".kml")
#     kml.write(outfile, prettyprint=True, precision=3)


try:
    import geojson
    from pygeoif.factories import shape
    # from pygeoif.geometry import Point
    # import sys
    import fastkml
    import fastkml.containers
    import fastkml.features
    import fastkml.styles
    from fastkml.geometry import create_kml_geometry
    # from fastkml.enums import AltitudeMode
except Exception as exc:
    print(f"[FAIL] KML generation: cannot import geojson/pygeoif/fastkml: {type(exc).__name__}: {exc}")
    print("       hint: install with 'python3 -m pip install --user geojson fastkml pygeoif'")
    shape = None

mirror_x_geometry = True

allfiles = mirror_geojson_files + mirror_geojson_files1 + mirror_geojson_files2

if shape is not None:
    for mirror_pair in allfiles:

        geojson_in=mirror_pair[0]
        gojson_out=mirror_pair[1]
        icon_url = mirror_pair[2]
        linecolor= mirror_pair[3]
        linewidth= mirror_pair[4]

        icon_scale=0.2

        # KML colors are AABBGGRR, with no leading '#'. Marble's KML parser
        # rejects '#'-prefixed colors as QColor(), which made point labels
        # invisible. Marble's default label color is black, so every point
        # layer now sets an explicit white label color.
        is_point_layer = False
        try:
            with open(geojson_in, 'r') as probe:
                probe_data = geojson.load(probe)
            is_point_layer = all(
                f.get('geometry', {}).get('type') == 'Point'
                for f in probe_data.get('features', [])
            )
        except Exception:
            pass

        outfile = pathlib.Path(gojson_out + ".kml")

        if not os.path.exists(geojson_in) or os.path.getsize(geojson_in) == 0:
            print(f"[SKIP] {outfile}: input is missing or empty: {geojson_in}")
            skipped.append(str(outfile))
            continue

        print(f"Creating: {outfile}")
        try:
            placemarks = []
            with open(geojson_in, 'r') as file_in:
                data = geojson.load(file_in)
            for feature in data['features']:

                geometry = shape(feature["geometry"])

                if mirror_x_geometry:
                    if feature['geometry'].type == "Point":
                        feature['geometry']['coordinates'][0] = (-1)*feature['geometry']['coordinates'][0]
                    elif feature['geometry'].type == "MultiLineString":
                        cord = feature['geometry']['coordinates']
                        for i in range(0, len(cord)):
                            for j in range(0, len(cord[i])):
                                cord[i][j][0]=(-1)*cord[i][j][0]
                    else:
                        print(f"Not supported geometry type: {feature['geometry'].type}")

                geometry = shape(feature["geometry"])
                kml_geometry = create_kml_geometry(
                    geometry,
                    tessellate=1,
                    # extrude=False,
                    # altitude_mode=AltitudeMode.relative_to_ground,
                    )

                styles = []
                if is_point_layer:
                    # For Point placemarks Marble keeps the inline KML style, so
                    # emit only the icon style and a plain white label color. Do
                    # not add line/poly styles to point layers.
                    if icon_url:
                        styles.append(fastkml.styles.IconStyle(icon_href=icon_url, scale=icon_scale))
                    if linecolor:
                        styles.append(fastkml.styles.LabelStyle(color=linecolor))
                else:
                    # Non-point styles are normally replaced by the DGML geodata
                    # style at load time, but these values are useful in other
                    # KML viewers and as a fallback.
                    if linecolor:
                        styles.append(fastkml.styles.LineStyle(color=linecolor, width=linewidth))
                        styles.append(fastkml.styles.PolyStyle(color=linecolor))
                style = fastkml.styles.Style(styles=styles)
                try:
                    name=feature["properties"]["name"]
                except Exception:
                    name=""
                if name is not None:
                    print(name)
                placemark = fastkml.features.Placemark(
                    name = name,
                    # description=feature["properties"]["FORMAL_EN"],
                    kml_geometry=kml_geometry,
                    styles=[style],
                )
                placemarks.append(placemark)

            document = fastkml.containers.Document(features=placemarks)
            kml = fastkml.KML(features=[document])
            kml.write(outfile, prettyprint=True, precision=3)
        except Exception as exc:
            print(f"[FAIL] {outfile}: {type(exc).__name__}: {exc}")
            failed.append(str(outfile))
        else:
            if not outfile.exists() or outfile.stat().st_size == 0:
                print(f"[FAIL] {outfile}: output is missing or empty")
                failed.append(str(outfile))
            else:
                print(f"[OK] created: {outfile}")
                generated.append(str(outfile))


#### constellation descriptions
# test for constellations info download
import re


def clean_div(string):
    string = string.replace('[<div class="zodiac-characteristics_text">\n', "<![CDATA[")
    string = string.replace("</div>]", "").replace('&lt;',"<").replace('&gt;',">")
    string = string + "<p>From: https://www.star-registration.com/blogs/constellations-and-zodiac-signs/an-overview-of-all-88-constellations</p>"
    string = string + "]]>"
    string = str(re.sub(r"\s\s+" , " ", str(string))).replace("\n","\r\n")
    return string


webpage="https://www.star-registration.com"
overview_url="https://www.star-registration.com/blogs/constellations-and-zodiac-signs/an-overview-of-all-88-constellations"

constelations=[]
try:
    import requests
    from bs4 import BeautifulSoup
except Exception as exc:
    print(f"[WARN] constellation descriptions: cannot import requests/bs4: {type(exc).__name__}: {exc}")
    print("       hint: install with 'python3 -m pip install --user requests beautifulsoup4'")
else:
    try:
        html = requests.get(overview_url, timeout=60).text
        soup = BeautifulSoup(html, "html.parser")

        const_title=soup.find_all(class_="constellation-card-title")
        for i in range(len(const_title)):
            string = const_title[i].text.replace('\n',"")
            const_title[i] = re.sub(r"\s\s+" , "", string)

        buttons_links=soup.find_all(class_="btn")

        if len(const_title) != len(buttons_links):
            raise ValueError(f"found {len(const_title)} constellation names but {len(buttons_links)} links")

        for link in buttons_links:
            hreff = link.get('href')
            if not hreff:
                raise ValueError("constellation link without href")
            constelation = hreff.split('constellation-')[-1:]
            print(f"Getting data for constellation: {constelation}")

            html = requests.get(webpage+hreff, timeout=60).text
            soup = BeautifulSoup(html, "html.parser")

            characteristics=str(soup.find_all(class_="zodiac-characteristics_text"))

            constelations.append( clean_div( str(characteristics)) )
    except Exception as exc:
        print(f"[WARN] constellation descriptions unavailable: {type(exc).__name__}: {exc}")
        constelations = []

#######
if not constelations:
    print(f"[SKIP] constellation descriptions: nothing downloaded, {constellations_mirror}.kml left unchanged")
    skipped.append(str(constellations_mirror + ".kml"))
else:
    try:
        from fastkml import kml
        from fastkml.utils import find_all
        from fastkml import Placemark
        from pathlib import Path

        file_path = Path(constellations_mirror +".kml")

        if not file_path.exists() or file_path.stat().st_size == 0:
            raise FileNotFoundError(f"KML file is missing or empty: {file_path}")

        k = kml.KML.parse(file_path, validate=False)

        features = k.features[0].features
        if len(constelations) + 1 != len(features):
            raise ValueError(f"downloaded {len(constelations)} descriptions for {len(features)} placemarks")

        ## 75 'Serpens Caput' OR 76 'Serpens Cauda' should be identical
        if len(features) <= 76:
            # No Serpens split to account for; assign what we have.
            for i in range(min(len(features), len(constelations))):
                features[i].description = str(constelations[i])
        else:
            for i in range(len(features)):
                if i == 75:
                    continue
                if i > 75:
                    i -= 1
                features[i].description = str(constelations[i])

        k.write(file_path)
        print(f"[OK] descriptions written: {file_path}")

        i=0
        placemarks = list(find_all(k, of_type=Placemark))
        for p in placemarks:
            print(f"{i}\t{p.name}")
            i += 1
    except Exception as exc:
        print(f"[WARN] constellation descriptions not written to {constellations_mirror}.kml: {type(exc).__name__}: {exc}")

# points = list(find_all(k, of_type=Point))
# for p in points:
#     print(p.geometry)


print()
print("=" * 60)
print(f"Generated: {len(generated)}")
for path in generated:
    print(f"  [OK]   {path}")
if skipped:
    print(f"Skipped: {len(skipped)}")
    for path in skipped:
        print(f"  [SKIP] {path}")
if failed:
    print(f"Failed: {len(failed)}")
    for path in failed:
        print(f"  [FAIL] {path}")
    print("Some steps failed; see messages above.")
    sys.exit(1)
print("All steps completed successfully.")
        
# points = list(find_all(k, of_type=Point))
# for p in points:
#     print(p.geometry)
    
    
    
    
    
    
    
    