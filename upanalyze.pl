#!/usr/bin/env perl
=begin comment

For analyzing the log information produced by uptest.pl

Provide the name of the log file to be analyzed as a command line option.
By default, the file "uptime_log.txt" will be analyzed.

Right now it prints a histogram of the dropped packet percentage for each hour.
The period can be changed from an hour by altering the constant
$BIN_SIZE_DEFAULT below.

note to self:
($sec,$min,$hour,$mday,$mon,$year,$wday,$yday,$isdst) = localtime(time);

=cut comment
use strict;
use warnings;

my $BIN_SIZE_DEFAULT = 60; #minutes;
my $bin_size = $BIN_SIZE_DEFAULT * 60;
my $LOG_FILE_DEFAULT = "uptest_log.txt";

my $log_file = $LOG_FILE_DEFAULT;
if (@ARGV) {
	$log_file = shift @ARGV;
}

my @data = build_data($log_file);

# Add an adaptive bin-size-determining subroutine?

print_graph(\@data, $bin_size);
# Replace with two subroutines:
# One that calculates totals for each bin, returning them in a data structure,
# And one that formats and prints those totals



#################### SUBROUTINES ####################

sub build_data {
	
	my ($log_file) = @_;
	
	open(my $log_fh, "<", $log_file) or
		die "Error: Cannot read logfile $log_file: $!";
	
	my @data;
	my $errors = 0;
	while (<$log_fh>) {
		
		if (m/^([0-9.]+),?\s+(\d{10})/) {
			push(@data, { success => $1, time => $2 } );
		} else {
			warn "Error: Line improperly formatted; skipping: $_\n";
			$errors++;
			if ($errors > 15) {
				die "Too many errors. Aborting.\n";
			}
		}
		
	}
	
	return @data;
}

sub print_graph {
	
	my ($dataref, $bin_size) = @_;
	my $WIDTH = 50;
	
	my $start_time = $dataref->[0]->{time};
	my $end_time = $dataref->[-1]->{time};
	
	# Calculations to determine the bin to start in
	my ($start_sec, $start_min) = (localtime($start_time))[0,1];
	my $start_bin_offset = (($start_min % $bin_size) * 60) + $start_sec;
	my $bin_start = $start_time - $start_bin_offset;
	my $bin_end = $bin_start + $bin_size;
	
	print "\n\t\t\t\t\tPacket Loss Histogram\n";
	print "\t      100% loss: |", '=' x $WIDTH, "|\n";
	my $pings = 0;
	my $replies = 0;
	for my $entry (@$dataref) {
		if ($$entry{time} >= $bin_end) {
			print scalar(localtime($bin_end - $bin_size)), ": ";
			disp_loss($pings, $replies, $WIDTH);
			$bin_end += $bin_size;
			$pings = 0;
			$replies = 0;
		}
		$pings++;
		my $success = 0;
		if ($$entry{success}) {
			$success = 1;
		}
		$replies += $success;
	}
}

sub disp_loss {
	my ($pings, $replies, $width) = @_;
	my $fraction = ($pings - $replies)/$pings;
	print "*" x int($fraction * $width), "\n";
}
