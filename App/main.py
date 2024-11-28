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
        pad_name = f"sink_{i}"
        sink_pad = streammux.get_request_pad(pad_name)
        src_pad = source_bin.get_static_pad("src")
        src_pad.link(sink_pad)

    # Add the inference engine
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    pgie.set_property("config-file-path", "./config/pgie1_config.txt")
    pipeline.add(pgie)

    # Add the on-screen display
    nvdsosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")
    pipeline.add(nvdsosd)

    # Add video convert and sink
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    pipeline.add(nvvidconv)
    sink = Gst.ElementFactory.make("nveglglessink", "video-output")
    sink.set_property("sync", False)
    pipeline.add(sink)

    # Link the pipeline elements
    streammux.link(pgie)
    pgie.link(nvdsosd)
    nvdsosd.link(nvvidconv)
    nvvidconv.link(sink)

    # Start the pipeline
    pipeline.set_state(Gst.State.PLAYING)

    # Create a main loop
    loop = GObject.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        pass

    # Stop the pipeline
    pipeline.set_state(Gst.State.NULL)

def create_source_bin(index, uri):
    """
    Create a source bin with uridecodebin for the given URI.
    """
    bin_name = f"source-bin-{index}"
    source_bin = Gst.Bin.new(bin_name)

    # Create uridecodebin
    uri_decode_bin = Gst.ElementFactory.make("nvurisrcbin", f"uri-decode-bin-{index}")
    uri_decode_bin.set_property("uri", uri)

    # Add the uridecodebin to the bin
    source_bin.add(uri_decode_bin)

    # Create a ghost pad for the bin
    def pad_added_cb(decodebin, pad, bin):
        sink_pad = bin.get_static_pad("src")
        if not sink_pad.is_linked():
            pad.link(sink_pad)

    uri_decode_bin.connect("pad-added", pad_added_cb)

    # Create ghost pad
    bin_pad = Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC)
    source_bin.add_pad(bin_pad)

    return source_bin

if __name__ == "__main__":
    sys.exit(main())
