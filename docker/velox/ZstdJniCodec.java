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

public class ZstdJniCodec implements CompressionCodec {

    @Override
    public String getDefaultExtension() {
        return ".zst";
    }

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
        }
    }
}
