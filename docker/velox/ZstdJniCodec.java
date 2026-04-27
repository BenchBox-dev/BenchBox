package io.benchbox.codec;

import com.github.luben.zstd.ZstdInputStream;
import com.github.luben.zstd.ZstdOutputStream;
import org.apache.hadoop.io.compress.CompressionCodec;
import org.apache.hadoop.io.compress.CompressionInputStream;
import org.apache.hadoop.io.compress.CompressionOutputStream;
import org.apache.hadoop.io.compress.Compressor;
import org.apache.hadoop.io.compress.Decompressor;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Hadoop CompressionCodec for Zstandard (.zst) backed by zstd-jni.
 *
 * The official apache/spark Docker image ships Hadoop 3.4.1 whose
 * ZStandardCodec requires native libhadoop compiled with zstd support, which
 * that image does NOT include.  This codec instead wraps ZstdInputStream /
 * ZstdOutputStream from the zstd-jni-*.jar already on the Spark classpath,
 * providing a pure-JVM decompression path for .zst files.
 *
 * Registration (in spark-defaults.conf or --conf):
 *   spark.hadoop.io.compression.codecs = io.benchbox.codec.ZstdJniCodec
 *
 * NOTE - read-only in BenchBox.  BenchBox only consumes .zst input data; it
 * never writes .zst output via Spark.  The compression (createOutputStream /
 * ZstdCompressionOutputStream) path is implemented for completeness but is
 * NOT exercised by any BenchBox workflow.  In particular,
 * ZstdCompressionOutputStream.finish() flushes but does not finalize the zstd
 * frame, so consumers of a written-and-not-closed stream would see truncated
 * data.  If a future workflow needs .zst writes, replace finish() with a
 * proper frame-finalization call (e.g. zout.close() with the underlying-
 * stream-ownership contract reviewed) and add a unit test.
 */
public class ZstdJniCodec implements CompressionCodec {

    @Override
    public String getDefaultExtension() {
        return ".zst";
    }

    // ── decompression ──────────────────────────────────────────────────────

    @Override
    public CompressionInputStream createInputStream(InputStream in) throws IOException {
        return new ZstdCompressionInputStream(new ZstdInputStream(in));
    }

    @Override
    public CompressionInputStream createInputStream(InputStream in, Decompressor decompressor)
            throws IOException {
        return createInputStream(in);
    }

    @Override
    public Class<? extends Decompressor> getDecompressorType() {
        return null;
    }

    @Override
    public Decompressor createDecompressor() {
        return null;
    }

    // ── compression ────────────────────────────────────────────────────────

    @Override
    public CompressionOutputStream createOutputStream(OutputStream out) throws IOException {
        return new ZstdCompressionOutputStream(new ZstdOutputStream(out));
    }

    @Override
    public CompressionOutputStream createOutputStream(OutputStream out, Compressor compressor)
            throws IOException {
        return createOutputStream(out);
    }

    @Override
    public Class<? extends Compressor> getCompressorType() {
        return null;
    }

    @Override
    public Compressor createCompressor() {
        return null;
    }

    // ── inner stream wrappers ──────────────────────────────────────────────

    private static final class ZstdCompressionInputStream extends CompressionInputStream {
        ZstdCompressionInputStream(ZstdInputStream zin) throws IOException {
            super(zin);
        }

        @Override
        public int read(byte[] b, int off, int len) throws IOException {
            return in.read(b, off, len);
        }

        @Override
        public int read() throws IOException {
            return in.read();
        }

        @Override
        public void resetState() throws IOException {
            // zstd frames are self-contained; nothing to reset for sequential reads.
        }
    }

    private static final class ZstdCompressionOutputStream extends CompressionOutputStream {
        private final ZstdOutputStream zout;

        ZstdCompressionOutputStream(ZstdOutputStream zout) throws IOException {
            super(zout);
            this.zout = zout;
        }

        @Override
        public void write(byte[] b, int off, int len) throws IOException {
            zout.write(b, off, len);
        }

        @Override
        public void write(int b) throws IOException {
            zout.write(b);
        }

        @Override
        public void finish() throws IOException {
            zout.flush();
        }

        @Override
        public void resetState() throws IOException {
            // Not required for single-frame zstd files.
        }
    }
}
