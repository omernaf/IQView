function iqview(data, fs, fc, nfft, options)
%%
% Open IQView Spectrogram Viewer with data piped directly from
%   Parameters:
%       data  - Complex vector of IQ samples (converted to float32 internally)
%       fs    - Sample rate in Hz
%       fc    - Center frequency in Hz
%       nfft  - order of fft performed by the app
%
% -f FILE, --file FILE  Path to the binary IQ file
% -t TYPE, --type TYPE  Data type (int16, float32, float64, complex64, complex128)
% -r RATE, --rate RATE  Sample rate in Hz
% -c FC, --fc FC        Center frequency in Hz
% -s FFT, --fft FFT     FFT bin size

arguments
    data (1,:) double = []
    fs double {mustBeScalarOrEmpty} = []
    fc double = []
    nfft double = []
    options.Title (1,1) string = ""
    options.ForceTempFile (1,1) logical = false
end

%%
data_single = single(data( :));
interleaved = zeros(2 * numel(data_single), 1, 'single');
interleaved(1 : 2 : end) = real(data_single);
interleaved(2 : 2 : end) = imag(data_single);
byte_data = typecast(interleaved, 'uint8');
total_bytes = numel(byte_data);

cmd_args = {'iqview', '-t', 'complex64'};
if ~isempty(data)
    if options.ForceTempFile
        temp_file_path = fullfile(tempdir, 'iqview_temp.iq');
        fid = fopen(temp_file_path, 'W');
        if fid == -1
            error('Failed to open temporary file for writing.');
        end
        fwrite(fid, byte_data, 'uint8');
        fclose(fid);
        cmd_args = [cmd_args, {'-f'}, {temp_file_path}];
    else
        cmd_args = [cmd_args, {'--stdin'}];
    end
end
if ~isempty(fs)
    cmd_args = [cmd_args, {'-r'}, {num2str(fs, '%.6g')}];
end
if ~isempty(fc)
    cmd_args = [cmd_args, {'-c'}, {num2str(fc, '%.6g')}];
end
if ~isempty(nfft)
    cmd_args = [cmd_args, {'-s'}, {num2str(nfft, '%d')}];
end
if strlength(options.Title) > 0
    cmd_args = [cmd_args, {'-n'}, {char(options.Title)}];
end

pb = java.lang.ProcessBuilder(cmd_args);
pb.redirectErrorStream(true);

proc = pb.start();
if ~isempty(data) && ~options.ForceTempFile
    stdin_stream = proc.getOutputStream();
    
    chunk_size = 64 * 1024 * 1024;
    for i = 1:chunk_size:total_bytes
        end_idx = min(i + chunk_size - 1, total_bytes);
        current_chunk = byte_data(i:end_idx);
        stdin_stream.write(current_chunk); 
    end

    stdin_stream.flush();
    stdin_stream.close(); % EOF - signals Python's sys.stdin.buffer.read() to return
end
end

