#!/usr/bin/env python
#Dan Blankenberg

import os, sys, gzip, tarfile, ftplib, time, tempfile

from galaxy import eggs
import pkg_resources
pkg_resources.require( "simplejson" )
import simplejson
from optparse import OptionParser
from galaxy.util.odict import odict

SPLIT_DELIMITER = ' '
JOIN_DELIMITER = '\t'
ENCODE_FTP_SERVER = 'encodeftp.cse.ucsc.edu'

def fix_values( value_dict ):
    mapping = { 'sex': { "F - Female": "F", "M - Male": "M" } }#, 'seqPlatform':{ '': DEFAULT_SEQPLATFORM } }
    for key, val in value_dict.iteritems():
        if key in mapping:
            for key2, val2 in mapping.iteritems():
                if key2 == val:
                    value_dict[key]=val2
    return value_dict

class TrackView( object ):
    def __init__( self ):
        self.attributes = {}

def parse_daf( daf_fh, log ):
    offset = None
    variables = None
    while True:
        offset = daf_fh.tell()
        line = daf_fh.readline()
        if not line:
            break
        if line.startswith( 'variables' ):
            variables = map( lambda x: x.strip(), line.split( SPLIT_DELIMITER, 1 )[1].split( ',' ) ) 
        if line.startswith( 'view' ):
            daf_fh.seek( offset )
            break
    if not variables:
        log.write( 'No variables detected!\n' )
    #at start of views, info needed
    views = {}
    
    while True:
        line = daf_fh.readline()
        if line.startswith( ( '#', '\n' ) ):
            continue
        if not line:
            break
        line = line.strip()
        fields = map( lambda x: x.strip(), line.split( SPLIT_DELIMITER, 1 ) )
        assert fields[0] == 'view', Exception( 'Malformed DAF' )
        view = TrackView()
        view.name = fields[1]
        assert view.name not in views, Exception( 'A view was defined twice: %s' % ( view.name ) )
        views[ view.name ] = view
        while True:
            line = daf_fh.readline().strip()
            if line.startswith( '#' ):
                continue
            if not line:
                break
            fields = map( lambda x: x.strip(), line.split( SPLIT_DELIMITER, 1 ) )
            view.attributes[ fields[0] ] = fields[1]
    return views, variables

def get_template_value( variable_name, name_template_dict, label_template_dict, mapping_dict, default_value_dict ):
    default_value = ''
    if variable_name in default_value_dict:
        default_value = default_value_dict[ variable_name ][ 'default_value' ]
        if default_value_dict[ variable_name ][ 'force_override' ]:
            return default_value
    if variable_name in name_template_dict:
        return name_template_dict[ variable_name ] or default_value
    if variable_name in mapping_dict:
        if mapping_dict[ variable_name ][ 'use_label' ]:
            return label_template_dict[ mapping_dict[variable_name][ 'field_name' ] ] or default_value
        else:
            return name_template_dict[ mapping_dict[variable_name][ 'field_name' ] ] or default_value
    return default_value

def main():
    parser = OptionParser()
    parser.add_option( "-n", dest="submission_name", help="submission name" )
    parser.add_option( "-f", dest="template_filename", help="template filename" )
    parser.add_option( "-m", dest="mapping_filename", help="mapping filename" )
    parser.add_option( "-v", dest="default_value_filename", help="default value filename" )
    parser.add_option( "-d", dest="ddf_filename", help=".ddf filename" )
    parser.add_option( "-r", dest="daf_filename", help="reference daf path" )
    parser.add_option( "-t", dest="tarball_filename", help="tarball filename (temp)" )
    parser.add_option( "-l", dest="log_filename", help="tarball filename (temp)" )
    parser.add_option( "-u", dest="ftp_login", help="ftp credentials" )
    parser.add_option( "-o", dest="upload_opts", help="upload options" )
    
    (options, args) = parser.parse_args()
    
    log = open( options.log_filename, 'wb' )
    
    if options.mapping_filename:
        mapping_dict = simplejson.loads( open( options.mapping_filename ).read() )
    else:
        mapping_dict = {}
    
    if options.default_value_filename:
        default_value_dict = simplejson.loads( open( options.default_value_filename ).read() )
    else:
        default_value_dict = {} 
    
    views, variables = parse_daf( open( options.daf_filename ), log )
    
    submission_name = options.submission_name
    ddf_filename = "%s.ddf" % submission_name
    daf_filename = options.daf_filename
    archive_name = "%s.tgz" % submission_name
    
    if options.tarball_filename:
        tarball_filename = options.tarball_filename
    else:
        tarball_filename = tempfile.NamedTemporaryFile( prefix = "encode_submission_%s" % ( submission_name  ) ).name
        open( tarball_filename, 'wb' ).close() #create file by name so it is not reused
    
    library_items = simplejson.loads(  open( options.template_filename ).read() )

    ddf_file = open( options.ddf_filename, 'wb' )
    now = int( time.time() )
    ddf_file.write( 'files\tview\t'  )
    for variable in variables:
        ddf_file.write( '%s\t' % ( variable ) )
    ddf_file.write( 'replicate\tseqPlatform\tlabVersion\n'  )
    
    filepaths = []
    for ldda_name, ldda_dict in library_items.iteritems():
        file_path = ldda_dict[ 'filename' ]
        name_template_dict = ldda_dict[ 'name_template' ]
        label_template_dict = ldda_dict[ 'label_template' ]
        try:
            name_template_dict = name_template_dict[name_template_dict.keys()[0]] #Multiple templates allowed in Galaxy, We assume only one template for ldda being submitted. 
            label_template_dict = label_template_dict[label_template_dict.keys()[0]] #Multiple templates allowed in Galaxy, We assume only one template for ldda being submitted.
            #TODO: allow checking multiple templates for values
        except:
            sys.stderr.write( "Missing metadata for: %s" % ldda_name)
            sys.exit()
        name_template_dict = fix_values( name_template_dict ) #this should be defined externally
        file_name = os.path.basename(file_path)
        filepaths.append(file_path)
        
        view_name = get_template_value( 'view', name_template_dict, label_template_dict, mapping_dict, default_value_dict )
        view = views.get( view_name )
        assert view is not None, Exception( 'View by name of "%s" was not found.' % ( view_name ) )
        #write out filename and view
        ddf_file.write( '%s\t%s\t' % ( file_name, view.name ) )
        #write out variables
        for variable in variables:
            ddf_file.write( '%s\t' % ( get_template_value( variable, name_template_dict, label_template_dict, mapping_dict, default_value_dict ) ) )
        #write out replicate, seqplatform, labversion
        ddf_file.write( '%s\t' % ( get_template_value( 'replicate', name_template_dict, label_template_dict, mapping_dict, default_value_dict ) ) )
        ddf_file.write( '%s\t' % ( get_template_value( 'seqPlatform', name_template_dict, label_template_dict, mapping_dict, default_value_dict ) ) )
        ddf_file.write( '%s\n' % ( get_template_value( 'labVersion', name_template_dict, label_template_dict, mapping_dict, default_value_dict ) ) )
    
    ddf_file.close()
    log.write( "writing DDF file done\n" )
    
    tarball = tarfile.open( tarball_filename, 'w:gz' )
    
    if options.upload_opts != 'up_datasets':
        #add dddf, unless only uploading datasets
        ddfti = tarfile.TarInfo( submission_name + ".ddf" )
        ddfti.mtime = now
        ddfti.size = os.path.getsize( options.ddf_filename )
        tarball.addfile( ddfti, file( options.ddf_filename ) )
        log.write( "adding %s to tarball\n" % ddfti.name )
    
    if options.upload_opts in [ "up_all", "up_datasets" ]:
        # Add datasets
        for path in filepaths:
            file_name = os.path.basename( path )
            ti = tarfile.TarInfo( file_name )
            ti.size = os.path.getsize( path )
            ti.mtime = now
            tarball.addfile( ti, file( path ) )
            log.write( "adding %s to tarball\n" % ti.name )
    
    if options.upload_opts in [ "up_all", "up_daf" ]:
        # Add daf 
        dafti = tarfile.TarInfo( submission_name + ".daf" )
        daf_path = options.daf_filename
        dafti.mtime = now
        dafti.size = os.path.getsize( daf_path )
        tarball.addfile( dafti, file( daf_path ) )
        
        log.write( "adding %s to tarball\n" % dafti.name )
    
    tarball.close()
    log.write( "closing tarball\n" )
    if options.upload_opts != "up_none":
        log.write( "uploading to encode\n" )
        user, password = options.ftp_login.split( ":", 1 )
        ftp = ftplib.FTP( ENCODE_FTP_SERVER, user, password )
        ftp.storbinary( "STOR " + submission_name + "_data.tgz", open( tarball_filename, "rb"  ), 1024 )
        log.write( "done uploading %s_data.tgz\n" % ( submission_name ) )
    
    if not options.tarball_filename:
        os.unlink( tarball_filename )
        log.write( "deleting temp tarball\n" )
    
    log.close()
    

if __name__ == '__main__': main()
