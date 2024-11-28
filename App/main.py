import sys
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject
import yaml

# Initialize GStreamer
Gst.init(None)

cameras = []

# Input file or stream
with open('./config/main-config.yaml') as yml_file:
    _ = yml_file.readline()
    config = yaml.safe_load(yml_file)
    
    num_cam = config['Main']['iCamNum']

    for i in range(num_cam):
        camera_tag = f"Cam{i + 1}"
        url = config[camera_tag]['sURI']
        cameras.append(url)

def main():
    # Initialize GStreamer
    Gst.init(None)

    # Create the GStreamer pipeline
    pipeline = Gst.Pipeline.new("multi-source-pipeline")

    # Create the stream muxer
    streammux = Gst.ElementFactory.make("nvstreammux", "stream-muxer")
    streammux.set_property("batch-size", len(cameras))
    streammux.set_property("width", 1920)
    streammux.set_property("height", 1080)
    streammux.set_property("batched-push-timeout", 4000000)
    pipeline.add(streammux)

    # Add sources and link them to the muxer
    for i, uri in enumerate(cameras):
        source_bin = create_source_bin(i, uri)
        pipeline.add(source_bin)
        sink_pad = streammux.get_request_pad(f"sink_{i}")
        src_pad = source_bin.get_static_pad("src")
        if not src_pad.link(sink_pad) == Gst.PadLinkReturn.OK:
            print(f"Error: Failed to link source {i} to streammux")
            sys.exit(1)

    # Add the Primary Inference Engine (PGIE)
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    pgie.set_property("config-file-path", "./config/pgie1_config.txt")
    pipeline.add(pgie)

    # Add the Secondary Inference Engine (SGIE)
    sgie = Gst.ElementFactory.make("nvinfer", "secondary-inference")
    sgie.set_property("config-file-path", "./config/sgie1_config.txt")
    pipeline.add(sgie)

    # Add the On-Screen Display (OSD)
    nvdsosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")
    pipeline.add(nvdsosd)

    # Add video convert and sink
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    pipeline.add(nvvidconv)

    sink = Gst.ElementFactory.make("nveglglessink", "video-output")
    sink.set_property("sync", False)
    pipeline.add(sink)

    # Link the pipeline elements
    if not streammux.link(pgie):
        print("Error: Failed to link streammux to PGIE")
        sys.exit(1)

    if not pgie.link(sgie):
        print("Error: Failed to link PGIE to SGIE")
        sys.exit(1)

    if not sgie.link(nvdsosd):
        print("Error: Failed to link SGIE to OSD")
        sys.exit(1)

    if not nvdsosd.link(nvvidconv):
        print("Error: Failed to link OSD to video convertor")
        sys.exit(1)

    if not nvvidconv.link(sink):
        print("Error: Failed to link video convertor to sink")
        sys.exit(1)

    # Start the pipeline
    pipeline.set_state(Gst.State.PLAYING)

    # Create a main loop
    loop = GObject.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("Pipeline interrupted")

    # Stop the pipeline
    pipeline.set_state(Gst.State.NULL)

def create_source_bin(index, uri):
    """
    Create a source bin with uridecodebin for the given URI.
    """
    bin_name = f"source-bin-{index}"
    source_bin = Gst.Bin.new(bin_name)

    # Create uridecodebin
    uri_decode_bin = Gst.ElementFactory.make("uridecodebin", f"uri-decode-bin-{index}")
    uri_decode_bin.set_property("uri", uri)
    source_bin.add(uri_decode_bin)

    # Create ghost pad for the bin
    bin_pad = Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC)
    source_bin.add_pad(bin_pad)

    # Callback to link dynamically created pads
    def pad_added_cb(decodebin, pad):
        ghost_pad = source_bin.get_static_pad("src")
        if not ghost_pad.is_linked():
            if not pad.link(ghost_pad) == Gst.PadLinkReturn.OK:
                print(f"Error: Failed to link decodebin pad to source bin {index}")
    
    uri_decode_bin.connect("pad-added", pad_added_cb)
    return source_bin

if __name__ == "__main__":
    sys.exit(main())
